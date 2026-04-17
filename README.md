# LocalWordle
1. To play the game, type

```bash
py main.py --web 
```

in a terminal. 

2. ctrl+click on the localhost link to open the game in your browser.
3. Type in a username to save your stats
4. Select language
5. Have fun

(6. use the wordlesolver script if the puzzle is too hard.)

You can reset your stats by typing the following in the terminal

```bash
py main.py --reset-stats Alice # all stats for both languages for the user
py main.py --reset-stats Alice --language da # only danish
py main.py --reset-stats Alice --language en # only english
```

# WordleSolver
1. select wordist by editing the wordlist line ('words', 'dkwords')
2. type in your grey letters in the GREY list.
3. type in your yellows and their positions in the YELLOWS dict.
4. Do the same for the potential greens.
5. Enjoy