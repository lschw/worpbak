# worpbak
worpbak is a snapshot backup script based on rsync

## Features
* Remote source or backup destination
* No configuration file needed
* Each backup is stored in a separate folder named as YYYY-MM-DD_HH_MM_SS
* Only changed files are copied, unmodified files are hardlinked to previous
  backup
* **Option to automatically track file movements and renamings in source folder
  via shadow copy of source folder. Moved and renamed files are still hardlinked
  to files from previous backups**
* Option to clean backups based on interval rules
* Script to create second external backup of all backups


## Requirements
* python3 (python2 can cause problems with non-ascii characters in file names)
* rsync
* ssh if either source or backup destination is remote
* bash shell
* shell commands rm, mv, find
* filesystem of backup must support hardlinks
* if the mv-record feature is used, filesystem of source must support hardlinks

## Installation
There is no installation required. Download the latest release, extract it and 
execute [worpbak](worpbak).

## Usage
worpbak needs no configuration file, all options are passed via command line
arguments. It may be useful to write a bash script to save the configuration.

### Example
    worpbak \
        --mv-record \
        --log-max-size=5 \
        --log-file=/path/to/logfile.log \
        --log-rotate=3
        --clean \
        --day=7 \
        --week=4 \
        --month=6 \
        --year=10 \
        /path/to/src/dir \
        /path/to/storage/dir

This creates a backup of the content of the folder "/path/to/src/dir" in the 
folder "/path/to/storage/dir/YYYY-MM-DD_HH_MM_SS" with the current date/time. 
If previous backups exist in the storage folder "/path/to/storage/dir", 
unmodified files regarding to the latest previous backup are hardlinked. The
backup is skipped, if there are no changes to the previous backup (can be
enforced with the --force flag).

In addition, the "--mv-record" flag enables the file movement record. This 
allows to hardlink files in the backup, which were moved or renamed in the 
source folder (see section about mv-record below).

The progress of worpbak is logged in the file "/path/to/logfile.log", which is
rotated if the file size exceed 5 MB. A maximum of 3 files is kept.

After the backup, the storage folder is cleaned. The algorithm keeps one backup 
of each of the last 7 days, one backup of each of the last 4 weeks, one backup 
of each of the last 6 months and one backup of each of the last 10 years. (see 
section about the clean-algorithm below)

Run

    worpbak --help
to see all available command line options.

## Explanation of the mv-record
Inherently it is not possible with rsync to keep track of renamed and moved
files. However, with a trick it is possible to simulate such behavior.

If not set explicitly, the mv-record is stored (for the example above) in
"/path/to/src/.worpbak_dir". The source's folder content is hardlinked into this
folder immediately after the backup. For this reason, the path to the mv-record
must be on the same partition as the source folder and the filesystem must
support hardlinks. This folder represents a (local) copy of the last backup. On
the next backup, this folder is simultaneously copied with the source folder to
the destinations, while keeping the hardlinked relation between the source and
mv-record. As rsync collects all files before sending and checks if they
already exist on the destination, moved and renamed files in the source are not
copied but directly hardlinked on the destination as the mapping from the
mv-record to the destination still exists. The rsync flag --no-inc-recursive is
important to prevent rsync from starting the copy process before collecting all
files, which can destroy the simultaneously transfering of source data and
mv-record data.

The mv-record is not required, the folder can safely be removed without
affecting the data in the backup. However, in that case one loses the
hardlinking feature of moved and renamed files, which will then be copied on the
next backup and not hardlinked to previous backups.

Please note that files deleted in the source folder are still available (and
use space) in the mv-record until the next backup, where the folder is synced
again to the source folder.

## Explanation of the clean algorithm
The clean feature has the purpose to remove certain backups from the storage 
folder to prevent an infinite growth of that folder. The clean algorithm bases 
on different interval rules, which have a certain amount of backups associated 
(set with the --year, --month, ... parameters).

The algorithm keeps the specified amount of backups for each interval.

Example: --day=7

1. Start with a date counter set to the date of the latest backup
2. Check if there is a backup 1 day back in time, if yes, mark this backup to
   keep
3. Decrease the date counter by 1 day and repeat 2., if the maximum backup 
   count of 7 is not yet reached and the date counter is still larger than the 
   oldest backup. Otherwise break.

For multiple intervals this process is repeated, starting with the shortest
interval (hour -> day -> week -> month -> year). Backups, which are already marked to
keep by a previous interval, do not count. The intervals are defined in such a
way that a decreasing by the interval length jumps back to the end of the
previous interval type:

Example, date is Wed., 2017-03-08 15:23:11

* 1 hour back: Wed., 2017-03-08 14:59:59
* 1 day back: Tue., 2017-03-07 23:59:59
* 1 week back: Sun., 2017-03-05 23:59:59
* 1 month back: Tue., 2017-02-28 23:59:59
* 1 year back: Wed., 2016-12-31 23:59:59

This procedure has the advantage that the kept backups are consistent to the
intervals in the long term, even if the backups are performed irregularly.
Always the last backup of an interval is kept, e.g. the backup of the last day 
of a week, month, year.

There is a small script in the folder [test/clean_simulation.py](test/clean_simulation.py), where the effect of the clean process with different intervals and backup times can be simulated.


## Clean script
With the script [worpbak-clean](worpbak-clean), one can manually clean up a
storage directory. The clean parameters are the same as for the main worpbak
script.

### Example:

    worpbak-clean \
        --day=7 \
        --week=4 \
        --month=6 \
        --year=10 \
        /path/to/storage/dir


## External backup script
The script [worpbak-ext](worpbak-ext) allows for a second external backup of the
storage directory, i.e. it copies the backups from the storage folder into an
external storage while preserving all hardlinks to previous backups. Already 
existing backups are skipped and the respective previous backup is used as 
mv-record or previous backup. Backups existing in the external storage but not
existing in the storage are not automatically removed. The 
[worpbak-clean](worpbak-clean) script can be used the clean up the external 
storage folder.

### Example:

Let's assume we have the following backups in /path/to/storage/dir:
    
    2017-03-08_23-59-59
    2017-04-07_23-59-59
    2017-05-07_23-59-59
    2017-06-08_23-59-59

and the following backups in /path/to/external/storage/dir

    2017-04-07_23-59-59
    2017-05-06_23-59-59

A call of

    worpbak-ext \
        --verbose \
        /path/to/storage/dir \
        /path/to/external/storage/dir

has the following effect:

* backup 2017-03-08_23-59-59 is copied
* backup 2017-04-07_23-59-59 is skipped as it already exists
* backup 2017-05-07_23-59-59 is copied with the backup
  /path/to/storage/dir/2017-04-07_23-59-59 used as mv-record and the backup 
  /path/to/external/storage/dir/2017-05-06_23-59-59 used as previous backup
* backup 2017-06-08_23-59-59 is copied with the backup
  /path/to/storage/dir/2017-05-07_23-59-59 used as mv-record and the backup
  in /path/to/external/storage/dir/2017-05-07_23-59-59 used as previous backup.

Finally, the backups in /path/to/external/storage/dir are

    2017-03-08_23-59-59
    2017-04-07_23-59-59
    2017-05-06_23-59-59
    2017-05-07_23-59-59
    2017-06-08_23-59-59
