#!/usr/bin/env python

#
# test program to simulate the clean process
#

import sys
import os
import datetime
import random
import logging

import sys
sys.path.append(os.path.realpath("../"))
import worpbak

# setup logging
log = logging.getLogger("worpbak")
log.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
log.addHandler(ch)

# define some arbitrary intervals
intervals = [
    worpbak.YearInterval(10),
    worpbak.MonthInterval(6),
    worpbak.WeekInterval(3),
    worpbak.DayInterval(7)
]

backups = []

# set a start date
date = datetime.datetime.strptime("2011-02-23_12-32-11", worpbak.date_fmt)

# test case
test = 2

# test case 1:
# simulate backup at (random) times and clean after ALL backup
if test == 0:
    for i in range(2000): # simulate 2000 backups
        
        # define time step
        if random.randint(0,10) > 2:
            diff = datetime.timedelta(
                days=random.randint(1,4)
            )
        else:
            diff = datetime.timedelta(
                hours=random.randint(1,10)
            )
        date = date+diff
        backups.append(worpbak.Backup(date))
    backups.sort(key=lambda x: x.date, reverse=True)

    backups = worpbak.clean(
        None, intervals, dry_run=True, backups=backups
    )
    print("\n")
    
    # create list of backups to keep
    backups_keep = []
    for backup in backups:
        if not backup.remove:
            backups_keep.append(backup)
    backups = backups_keep
    log.info(worpbak.fmt_backup_list(backups, True))


# test case 2:
# simulate backup at (random) times and clean after EACH backup
else:
    for i in range(2000): # simulate 2000 backups
        
        # define time step
        if random.randint(0,10) > 2:
            diff = datetime.timedelta(
                days=random.randint(1,4)
            )
        else:
            diff = datetime.timedelta(
                hours=random.randint(1,10)
            )
        date = date+diff
        backups.append(worpbak.Backup(date))
        backups.sort(key=lambda x: x.date, reverse=True)
        
        os.system("clear")
        
        backups = worpbak.clean(
            None, intervals, dry_run=True, backups=backups
        )
        
        # keep only backups marked to keep
        backups_keep = []
        for backup in backups:
            if not backup.remove:
                backups_keep.append(backup)
        backups = backups_keep
