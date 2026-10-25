Study 3 power estimates (prereg/ADDENDUM_4_study3.md, "Detectable effect"), from scripts/power_study3_resample.py.
Pilot games are resampled into simulated main runs; an effect is injected into the second arm listed; the frozen
per-game test, Holm and decision rule decide. Roots are given in this order (it sets the game labels):

power_as_planned.txt   python -I scripts/power_study3_resample.py $PWD runs/pilot_s3 runs/pilot_s3b --reps 300 --perms 1000 --deltas 0,0.10,0.15,0.20,0.30
                       (made with the script before its --arms option was added; the committed script reproduces it
                        exactly with the default --arms P0,PF,PE,PT,PC and --games 36)
power_5arms_54.txt     ... --reps 200 --perms 1000 --deltas 0.15,0.20 --games 54 --arms P0,PF,PE,PT,PC   (810 games)
power_4arms_45.txt     ... --reps 200 --perms 1000 --deltas 0.15,0.20 --games 45 --arms P0,PE,PT,PC      (540 games)
power_3arms_54.txt     ... --reps 200 --perms 1000 --deltas 0.15,0.20 --games 54 --arms P0,PT,PC         (486 games)

The printed phrase "PF games entering the primary" means games of the injected arm (PE or PT in the last two files).
Limitation: decisions are flipped one by one, ignoring that a challenge ends the round or can eliminate a partner;
the direction of the resulting bias is unknown.
