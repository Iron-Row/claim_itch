# claim_itch
Automate claiming itch.io games. The script scans sources like reddit megathreads for game URLs then claims them.

## Installation
Windows instructions, you can adapt them for linux/mac as pointed out by /u/farmerbb:

1. Install [python](https://www.python.org/downloads/).
2. Install [Firefox](https://www.mozilla.org/firefox/).
3. [Download](https://github.com/Iron-Row/claim_itch/releases/latest/) the script (claim_itch.py) into a folder of your choice.
4. Download [geckodriver](https://github.com/mozilla/geckodriver/releases) and put the .exe in the same folder as the script (or in your [PATH](https://www.howtogeek.com/118594/how-to-edit-your-system-path-for-easy-command-line-access/)).
5. Open the folder. Click "File" then open Powershell (or Command Prompt). This is where we will execute commands and run the script.
6. Install required packages by typing the command `python -m pip install beautifulsoup4 lxml requests selenium` and click enter to execute it.

## Usage

(Optional) *Manually add missing megathreads as described in Tip D below*.

1. Run the script by typing the command `python claim_itch.py` and clicking enter.
2. The script will print its progress on the screen.
3. After it collects game links. It will open firefox and go to itch.io.
4. Log in, then click enter in the script window.
5. It'll print its progress as it claims games. Then print a summary of the results.

## Tips

**A. How to stop the script while it's running?**

Click Ctrl+C.

**B. How to check if new games where posted?**

Run the command `python claim_itch.py --recheck`.

**C. How to see non-claimable games that I need to download?**

Run `python claim_itch.py --show-history`

**D. How to add more places to check for games?**

It supports reddit threads and itch.io sales/collections. Open the script in Notepad and add the link to the `SOURCES` variable. I might make it easier later.

**E. Why can't I see captcha images?**

I disabled images by default to save bandwidth. Use the `--enable-images` option. Or use the audio captcha by clicking the [headphone icon](https://lh3.googleusercontent.com/K3-D1VX2E3fWD4rHRoqqmogPU-a_SV48lDideMH3bKSGNUE0Z-UMP0R0HGlAL2I=w305-h458). I found audio captcha to be easier.

**F. It stopped before claiming all games.**

The code cannot handle all kinds of games on itch. You can use the `--ignore` option to continue claiming games despite an error. If there is any output that could be useful to fix the bug, please send it to me.

**G. How to see all the script options?**

Run `python claim_itch.py --help`

**H. What are the side effects of the script?**

* The history is stored in a file of your choice or a default file where you run the script (see `python claim_itch.py --help`).
* A log is stored in a default location where you run the script.
* Another log is left by geckodriver.

**I. Is the script safe?**

It doesn't do anything shady, but it can. The code has access to your computer, files, the internet, and controls a browser where you'll enter your itch password. Anyone can review the code, but that doesn't mean someone will.
