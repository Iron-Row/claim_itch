'''
ClaimItch/0.11

requirements:
- python (tested on 3.8)
- requests
- beautiful soup
- lxml
- selenium
- firefox
- geckodriver

files and variables:
- SOURCES variable:   includes itch sales/collections or reddit threads you want check, pass --recheck to retcheck them
- history file:       includes the results of the current run so they can be used in future runs
                      see the HISTORY_KEYS variable
- log file

todo - functionality:
- better interface for SOURCES
- seperate always-free download-only games like https://leafxel.itch.io/hojiya
- when discovering a game connected to a sale, check out the sale
- games that redirect to a sale
- notification of new script version
- download non-claimable games?
- login?
- follow discovered reddit threads?

todo - coding:
- the steamgifts source is huge, could probably be optimized 'https://itch.io/c/537762/already-claimed-will-be-on-sale-again'
- handle network errors?
- debug mode that enables breakpoints
- log exceptions and urls on error
- use classes?
- edge case: non writable config location - would do the work but loss history
- intersection between SOURCES and discovered collections in has_more?
- confirm that the keys before & after don't need to be checked in reddit's json
- proper log
- proper config
- claim() return values
- "selenium.common.exceptions.ElementNotInteractableException: Message: Element <a class="button buy_btn" href=".."> could not be scrolled into view"
- selenium's performance?
- less strict parsing / navigation (use .lower) / fuller regex (to work with match and search)
- pylint
- a claimable game was recorded as dl_only, was it changed? https://melessthanthree.itch.io/lucah
'''

import os
import sys
import re
import json
import html
import argparse
import requests
from time import sleep, time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException


# add any itch sale/collection or reddit thread to this set
SOURCES = {
    ## Not updated recently
    #'https://itch.io/c/757294/games-to-help-you-stay-inside',
    #'https://itch.io/c/759545/self-isolation-on-a-budget',
    #'https://itch.io/c/840421/paid-gone-free-sales',
    #'https://old.reddit.com/r/GameDeals/comments/fkq5c3/itchio_a_collecting_compiling_almost_every_single',
    #'https://old.reddit.com/r/FreeGameFindings/comments/fka4be/itchio_mega_thread/',
    #'https://old.reddit.com/r/FreeGameFindings/comments/fxhotl/itchio_mega_thread/',
    #'https://old.reddit.com/r/FreeGameFindings/comments/gbcjdn/itchio_mega_thread_3/',
    #'https://old.reddit.com/r/FreeGameFindings/comments/gkz20p/itchio_mega_thread_4/',
    #'https://old.reddit.com/r/FreeGameFindings/comments/hbkz5o/itchio_mega_thread_5/',
    #'https://old.reddit.com/r/FreeGameFindings/comments/hqjptv/itchio_mega_thread_6/',
    ## Disabled because it take a long time
    #'https://itch.io/c/537762/already-claimed-will-be-on-sale-again',
    'https://old.reddit.com/r/FreeGameFindings/comments/i4ywei/itchio_mega_thread_7/',
    'https://old.reddit.com/r/FreeGameFindings/comments/ipp4xn/itchio_mega_thread_8/',
}


PATTERNS = {
    'itch_collection': r'.+itch\.io/c/.+',
    'itch_sale': r'.+itch\.io/s/.+',
    'itch_group': r'.+itch\.io/[sc]/\d+/.+', # sale or collection
    'reddit_thread': r'.+(?P<thread>reddit\.com/r/.+/comments/.+)/.+',
    'itch_game': r'(http://|https://)?(?P<game>.+\.itch\.io/[^/?]+)'
}


USER_AGENT = 'ClaimItch/0.11'


HISTORY_KEYS = [
    'urls',           # discovered game urls
    'claimed',        # claimed games
    'has_more',       # a sale, collection, or game that is connected to more sales
    'checked_groups', # a sale/collection that was checked for games, pass --recheck-groups to recheck it
    'dl_only',        # game is not claimable
    'dl_only_old',    # downloadable game you want to skip for now
    'always_free',    # downloadable game that is always free
    'web',            # game is not claimable or downloadable, web game
    'downloaded',     # games that were downloaded (edit this manually)
    'buy',            # game is not free
    'removed',        # game does not exist
    'error',          # games that broke the script
    'old_error',      # games that broke the script but were fixed later
]

PROCESSED_GAMES = ('claimed', 'dl_only', 'dl_only_old', 'downloaded', 'buy', 'removed', 'web', 'always_free')


class ParsingError(Exception):
    def __init__(self, url, *args, **kwargs):
        # breakpoint()
        self.url = url
        super().__init__(url, *args, **kwargs)


def extract_from_itch_group(group_page):
    '''
    INPUT  html sale or collection page
    OUTPUT urls of all games, urls of games that avie noted is connected to more sales
    '''
    soup = BeautifulSoup(group_page, 'lxml')
    ended = soup.find_all('div', class_ = 'not_active_notification')
    urls, more = set(), set()
    if ended:
        print(" Sale ended")
        return urls, more
    games = soup.find_all('div', class_='game_cell')
    for game in games:
        url = game.find('a').get('href')
        urls.add(url)
        if game.find('div', class_='blurb_outer') is not None:
            more.add(url)
    return urls, more


def get_from_itch_group(group_url, sleep_time=15, max_page=None, sale=False):
    '''
    INPUT  itch.io collection url
    OUTPUT see extract_urls
    '''
    if sale:
        max_page = 1 # sales don't seem to have pages
    page = 1
    urls = set()
    has_more = set()
    while max_page is None or page <= max_page:
        print(f' getting page {page}')
        params = {'page': page} if not sale else None
        res = requests.get(group_url, params=params)
        if res.status_code == 404:
            break
        elif res.status_code != 200:
            # breakpoint()
            res.raise_for_status()
        page += 1
        new_urls, new_more = extract_from_itch_group(res.text)
        urls.update(new_urls)
        has_more.update(new_more)
        print(f' sleeping for {sleep_time}s')
        sleep(sleep_time)
    print(f' got {len(urls)} games')
    return urls, has_more


def get_from_reddit_thread(url, sleep_time=15):
    '''
    INPUT  reddit thread url
    OUTPUT itch.io game urls, itch.io groups (sales, collections)
    '''
    global USER_AGENT, PATTERNS

    # https://www.reddit.com/dev/api#GET_comments_{article}
    # https://github.com/reddit-archive/reddit/wiki/JSON
    base_url = f"https://{re.match(PATTERNS['reddit_thread'], url)['thread']}" # does not end with /
    urls = set()
    has_more = set()

    chains = ['']
    while len(chains) > 0:
        current_chain = chains.pop()
        print(f' getting a comment chain {current_chain}')
        json_url = base_url + current_chain + '.json?threaded=false'
        res = requests.get(json_url, headers={'User-Agent': USER_AGENT})
        if res.status_code != 200:
            res.raise_for_status()
        data = res.json()
        for listing in data:
            if listing['kind'].lower() != 'listing':
                raise ParsingError(json_url)
            children = listing['data']['children']
            for child in children:
                text = None
                if child['kind'] == 't3':
                    text = child['data']['selftext_html']
                elif child['kind'] == 't1':
                    text = child['data']['body_html']
                elif child['kind'] == 'more':
                    chains.extend(['/thread/' + chain for chain in child['data']['children']])
                else:
                    raise ParsingError(json_url)
                if text is not None and len(text) > 0:
                    soup = BeautifulSoup(html.unescape(text), 'lxml')
                    new_urls = set(a.get('href') for a in soup.find_all('a'))
                    urls.update(url for url in new_urls if re.match(PATTERNS['itch_game'], url))
                    has_more.update(url for url in new_urls if re.match(PATTERNS['itch_group'], url))
        print(f' sleeping for {sleep_time}s')
        sleep(sleep_time)
    print(f' got {len(urls)} games | {len(has_more)} collections/sales')
    return urls, has_more


def get_urls(url, sleep_time=15, max_page=None):
    global PATTERNS

    print(f'getting games from {url}')
    if re.match(PATTERNS['itch_collection'], url):
        return get_from_itch_group(url, sleep_time, max_page)
    elif re.match(PATTERNS['itch_sale'], url):
        return get_from_itch_group(url, sleep_time, sale=True)
    elif re.match(PATTERNS['reddit_thread'], url):
        return get_from_reddit_thread(url, sleep_time)
    else:
        # breakpoint()
        raise NotImplementedError(f'{url} is not supported')


def claim(url, driver):
    '''
    INPUTS
      url     game url
      driver  a webdriver for a browser that is logged in to itch.io
    OUTPUT
      status
        'claimed'           success
        'dl_only'           cannot be claimed
        'web'               cannot be claimed or downloaded, web game
        'buy'               not for sale
        'claimed has_more'  success, and indicaes that the game is connected to another sale
        'removed'           game does not exist
        'always_free'       dl_only game that is always free
    '''
    global PATTERNS

    url = f"https://{re.search(PATTERNS['itch_game'], url)['game']}"
    print(f'handling {url}')

    driver.get(url)
    original_window = driver.current_window_handle
    assert len(driver.window_handles) == 1

    # removed game
    try:
        driver.find_element_by_css_selector('div.not_found_game_page')
        return 'removed'
    except NoSuchElementException:
        pass

    # already owned
    try:
        if 'You own this' in driver.find_element_by_css_selector('div.purchase_banner_inner h2').get_attribute('textContent'):
            print(f' already claimed: {url}')
            return 'claimed'
    except NoSuchElementException:
        pass

    # check if claimable, download only, or a web game
    try:
        buy = driver.find_element_by_css_selector('div.buy_row a.buy_btn')
    except NoSuchElementException:
        try:
            buy = driver.find_element_by_css_selector('section.game_download a.buy_btn')
        except NoSuchElementException:
            try:
                driver.find_element_by_css_selector('div.uploads')
                print(f' download only: {url}')
                return 'dl_only'
            except NoSuchElementException:
                try:
                    driver.find_element_by_css_selector('div.html_embed_widget')
                    print(f' web game: {url}')
                    return 'web'
                except NoSuchElementException as nse_e:
                    raise ParsingError(url) from nse_e

    if 'Download Now' in buy.get_attribute('textContent'):
        try:
            sale_rate = driver.find_element_by_css_selector('.sale_rate')
        except NoSuchElementException as nse_e:
            print(f' always free: {url}')
            return 'always_free'
        else:
            if '100' in sale_rate.get_attribute('textContent'):
                print(f' download only: {url}')
                return 'dl_only'
            else:
                raise ParsingError(url)
    elif 'buy now' in buy.get_attribute('textContent').lower():
        print(f' buy: {url}')
        return 'buy'
    elif 'pre-order' in buy.get_attribute('textContent').lower():
        print(f' buy (pre-order): {url}')
        return 'buy'
    # claim
    elif 'Download or claim' in buy.get_attribute('textContent'):
        #buy.location_once_scrolled_into_view
        #buy.click()
        driver.get(f'{url}/purchase')

        try:
            no_thanks = driver.find_element_by_css_selector('a.direct_download_btn')
        except NoSuchElementException as nse_e:
            raise ParsingError(url) from nse_e

        if 'No thanks, just take me to the downloads' in no_thanks.get_attribute('textContent'):
            no_thanks.click()

            # in case the download page opens in a new window
            original_window = switch_to_new_window(driver, original_window)

            try:
                claim_btn = driver.find_element_by_css_selector('div.claim_to_download_box form button')
            except NoSuchElementException as nse_e:
                raise ParsingError(url) from nse_e

            if 'claim' in claim_btn.get_attribute('textContent').lower():
                claim_btn.click()

                try:
                    message = driver.find_element_by_css_selector('div.game_download_page div.inner_column p')
                except NoSuchElementException as nse_e:
                    raise ParsingError(url) from nse_e

                if 'for the promotion' in message.get_attribute('textContent'):
                    print(f' just claimed | part of a sale: {url}')
                    return 'claimed has_more'
                if 'You claimed this game' in message.get_attribute('textContent'):
                    print(f' just claimed: {url}')
                    return 'claimed'
                else:
                    raise ParsingError(url)
            else:
                raise ParsingError(url)
        else:
            raise ParsingError(url)
    else:
        raise ParsingError(url)


def create_driver(enable_images=False, mute=False):
    options = webdriver.firefox.options.Options()
    if not enable_images:
        options.set_preference('permissions.default.image', 2)
    if mute:
        options.set_preference('media.volume_scale', '0.0')
    if os.path.exists('geckodriver.exe'):
        driver = webdriver.Firefox(options=options, executable_path='geckodriver.exe')
    else:
        # geckodriver should be in PATH
        driver = webdriver.Firefox(options=options)
    driver.implicitly_wait(10)
    return driver


def switch_to_new_window(driver, original_window):
    '''If a new window was opened, switch to it'''
    sleep(1)
    if len(driver.window_handles) > 1:
        new_handle = None
        for window_handle in driver.window_handles:
            if window_handle != original_window:
                new_handle = window_handle
                break
        driver.close()
        driver.switch_to.window(new_handle)
        return new_handle
    return original_window


def log(name, data):
    with open(name, 'a') as f:
        for k, v in data.items():
            f.write(k + ': ' + str(v) + '\n')


def load_history(name):
    global HISTORY_KEYS

    try:
        f = open(name, 'r')
        with f:
            data = json.load(f)
        print(f'loaded history from file {name}')
    except FileNotFoundError:
        data = dict()
        print(f'new history file will be created: {name}')
    history = {k: set(data.get(k, [])) for k in HISTORY_KEYS}
    return history


def save_history(name, data):
    print(f'writing history to file {name}')
    with open(name, 'w') as f:
        json.dump({k: list(v) for k, v in data.items()}, f, indent=2)


def print_summary(history_file, history):
    global SOURCES, PATTERNS, PROCESSED_GAMES

    print('\nSUMMARY')

    if not os.path.exists(history_file):
        print(f'No history is stored in {history_file}')
        return

    print(f'History stored in {history_file}')
    print()

    print(f'Using {len(SOURCES)} main sources (use --recheck to recheck them)')
    print(f"Discovered {len(history['urls'])} games")
    print(f"Claimed {len(history['claimed'])} games")
    not_processed = history['urls'].difference(*map(history.get, PROCESSED_GAMES))
    print(f"{len(not_processed)} games should be claimed on the next run")
    print()

    itch_groups = set(filter(re.compile(PATTERNS['itch_group']).match, history['has_more']))
    itch_games = set(filter(re.compile(PATTERNS['itch_game']).match, history['has_more']))
    print(f"{len(itch_groups)} discovered collections / sales should be checked on the next run")
    print(f"{len(history['checked_groups'])} discovered collections / sales were checked (use --recheck-groups to recheck them)")
    print(f"{len(itch_games)} discovered games are connected to sales that may not have been checked")
    print(f"{len(history['removed'])} games were removed or invalid")
    print()

    print(f"Play {len(history['web'])} non-claimable and non-downloadable games online:")
    for url in history['web']:
        print(f'  {url}')
    print()

    print(f"Download {len(history['dl_only'])} non-claimable games manually:")
    for url in history['dl_only']:
        print(f'  {url}')
    print(f"{len(history['always_free'])} downloadable games are always free (not listed above)")
    print(f"{len(history['downloaded'])} games were marked as downloaded (to mark games: move them in the history file from 'dl_only' to 'downloaded')")
    print(f"{len(history['dl_only_old'])} downloadable games were skipped (moved to 'dl_only_old')")
    print()

    print(f"Buy {len(history['buy'])} non-free games.")
    print()

    print(f"Error encountered in {len(history['error'])} games (some maybe already solved):")
    for url in history['error']:
        print(f'  {url}')
    print()


def get_urls_and_update_history(history, sources, itch_groups):
    '''
    INPUT
      history      a dict that'll be updates as `sources` are processed
      sources      sources to get links from
      itch_groups  itch sales/collections in `sources` that should be marked as checked in `history`
    '''
    for i, source in enumerate(sources):
        print(f'{i+1}/{len(sources)}')
        new_urls, new_more = get_urls(source)
        history['urls'].update(new_urls)
        history['has_more'].update(new_more)
    history['checked_groups'].update(itch_groups)
    history['has_more'].difference_update(history['checked_groups'])


def main():
    global SOURCES, HISTORY_KEYS, PROCESSED_GAMES

    run_time = int(time())
    script_name = os.path.basename(os.path.splitext(sys.argv[0])[0])
    log_file = f'{script_name}.log.txt'
    default_history_file = f'{script_name}.history.json'
    log(log_file, {'# new run': run_time})

    arg_parser = argparse.ArgumentParser(
        description=f'Claim free itch.io games in an itch.io sale/collection or reddit thread. \
                     Writes the results (game links, claimed games, ..) to history_file. Logs to {log_file}')
    arg_parser.add_argument('history_file', nargs='?', help=f'a json file generated by a previous run of this script (default: {default_history_file})')
    arg_parser.add_argument('--show-history', action='store_true', help='show summary of history in history_file and exit')
    arg_parser.add_argument('--recheck', action='store_true', help='reload game links from SOURCES')
    arg_parser.add_argument('--recheck-groups', action='store_true', help='reload game links from discovered itch collections / sales')
    arg_parser.add_argument('--enable-images', action='store_true', help='load images in the browser while claiming games')
    arg_parser.add_argument('--mute', action='store_true', help='automatically mute while claiming games')
    arg_parser.add_argument('--ignore', action='store_true', help='continue even if an error occurs when handling a game')
    args = arg_parser.parse_args()

    if args.history_file is not None:
        history_file = args.history_file
    else:
        history_file = default_history_file
    history = load_history(history_file)
    log(log_file, {'history_file': history_file})
    log(log_file, {k: len(v) for k, v in history.items()})

    if args.show_history:
        print_summary(history_file, history)
        sys.exit(0)

    # getting game links
    itch_groups = set(filter(re.compile(PATTERNS['itch_group']).match, history['has_more']))
    check_sources = not os.path.exists(history_file) or args.recheck
    check_groups = len(itch_groups) > 0 or args.recheck_groups
    if check_sources or check_groups:
        print('will reload game urls from the internet')
        # keep getting newly discovered sales/collections
        first_pass = True
        while True:
            target_sources = set()
            itch_groups = set(filter(re.compile(PATTERNS['itch_group']).match, history['has_more']))
            if first_pass:
                if check_sources:
                    target_sources.update(SOURCES)
                if args.recheck_groups:
                    itch_groups.update(history['checked_groups'])
            else:
                if len(itch_groups) == 0:
                    break
                else:
                    print('getting links from newly discovered sales/collections')
            target_sources.update(itch_groups)
            get_urls_and_update_history(history, target_sources, itch_groups)
            first_pass = False
            log(log_file, {'## got links': time(), 'sources': target_sources, 'urls': history['urls'], 'has_more': history['has_more']})
    else:
        print('using game urls saved in the history file')
        print(' pass the option --recheck and/or --recheck-groups to reload game urls from the internet')

    # claiming games
    url = None
    sleep_time = 15
    try:
        ignore = set().union(*map(history.get, PROCESSED_GAMES))
        valid = history['urls'].difference(ignore)
        if len(valid) > 0:
            with create_driver(args.enable_images, args.mute) as driver:
                driver.get('https://itch.io/login')
                # manually log in
                input('A new Firefox window was opened. Log in to itch then click enter to continue')
                for i, url in enumerate(valid):
                    print(f"{i+1}/{len(valid)} ({len(history['urls'])})")
                    if url not in ignore:
                        try:
                            result = claim(url, driver)
                        except ParsingError as pe:
                            if not args.ignore:
                                raise
                            history['error'].add(pe.url)
                            print(f'Unknown Error: skipping {pe.url}')
                        else:
                            if url in history['error']:
                                history['error'].remove(url)
                                history['old_error'].add(url)
                            if 'claimed' in result:
                                history['claimed'].add(url)
                            if 'web' in result:
                                history['web'].add(url)
                            if 'has_more' in result:
                                history['has_more'].add(url)
                            if 'buy' in result:
                                history['buy'].add(url)
                            if 'removed' in result:
                                history['removed'].add(url)
                            if 'always_free' in result:
                                history['always_free'].add(url)
                                continue
                            if 'dl_only' in result:
                                history['dl_only'].add(url)
                            print(f' sleeping for {sleep_time}s')
                        sleep(sleep_time)
    except ParsingError as pe:
        history['error'].add(pe.url)
        raise
    except Exception as e:
        if url is not None:
            history['error'].add(url)
        raise
    finally:
        print()
        save_history(history_file, history)
        print_summary(history_file, history)


if __name__ == '__main__':
    main()
