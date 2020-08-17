# worpbak - a snapshot backup script based on rsync
# Copyright (C) 2017 Lukas Schwarz
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import sys
import os
import re
import datetime
import subprocess
import logging
import random

version = "0.2.0"

# regular expression for valid backup folder
backup_regex = r"^([0-9]{4})-([0-9]{2})-([0-9]{2})_" \
                "([0-9]{2})-([0-9]{2})-([0-9]{2})$"

# date format for backup folders
date_fmt = '%Y-%m-%d_%H-%M-%S'

# path to ssh-key file
ssh_key = None


class Backup:
    def __init__(self, date):
        self.date = date # date of backup
        self.remove = False # flag whether to remove backup
        self.msg = None # info message

    def as_str(self):
        return self.date.strftime(date_fmt)


class Interval:
    def __init__(self, maxn, size):
        self.maxn = maxn # maximum number of backups within this interval
        self.size = size # interval size in days (used for sorting)

    def in_boundary(self, date_start, date_check):
        """
        Check if date 'date_check' is within the interval boundary starting
        from date `date_start` backwards in time
        """
        boundary = self.lower_boundary(date_start)
        return boundary < date_check and date_check <= date_start

    def lower_boundary(self, date):
        """
        Return the lower boundary of this interval starting from `date`
        backwards in time
        """
        pass


class YearInterval(Interval):
    def __init__(self, maxn):
        Interval.__init__(self, maxn, 365)

    def lower_boundary(self, date):
        tt = date.timetuple()
        diff = datetime.timedelta(
            days=tt.tm_yday-1,
            hours=date.hour,
            minutes=date.minute,
            seconds=date.second+1
        )
        return date - diff


class MonthInterval(Interval):
    def __init__(self, maxn):
        Interval.__init__(self, maxn, 30)

    def lower_boundary(self, date):
        diff = datetime.timedelta(
            days=date.day-1,
            hours=date.hour,
            minutes=date.minute,
            seconds=date.second+1
        )
        return date-diff


class WeekInterval(Interval):
    def __init__(self, maxn):
        Interval.__init__(self, maxn, 7)

    def lower_boundary(self, date):
        tt = date.timetuple()
        diff = datetime.timedelta(
            days=tt.tm_wday,
            hours=date.hour,
            minutes=date.minute,
            seconds=date.second+1
        )
        return date-diff


class DayInterval(Interval):
    def __init__(self, maxn):
        Interval.__init__(self, maxn, 1)

    def lower_boundary(self, date):
        diff = datetime.timedelta(
            hours=date.hour,
            minutes=date.minute,
            seconds=date.second+1
        )
        return date-diff


class HourInterval(Interval):
    def __init__(self, maxn):
        Interval.__init__(self, maxn, 1./24)

    def lower_boundary(self, date):
        diff = datetime.timedelta(
            minutes=date.minute,
            seconds=date.second+1
        )
        return date-diff


class LogMsgFormatter(logging.Formatter):
    info_fmt = logging.Formatter("%(message)s")
    error_fmt = logging.Formatter("[%(levelname)s] %(message)s")
    def format(self, record):
        if record.levelno < logging.WARNING:
            return self.info_fmt.format(record)
        else:
            return self.error_fmt.format(record)


def shell_cmd(cmd, callback=None, raise_exc=False):
    """
    Execute external shell command

    callback : function which is called for each output line from running
               process. If the functions does not return True, the process
               will be killed
    raise_exc : if True, an exception will be thrown if the external command
                does not have an exit code of 0

    returns ret,output
        ret : return code of command
        output : all lines of output from process as list
    """
    output = [] # buffer for process output

    with subprocess.Popen(cmd, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, shell=True,
            executable="/bin/bash") as process:
        for line in process.stdout:
            line = line.decode("utf-8").strip()
            if line == "":
                continue
            output.append(line)
            if callback:
                if not callback(line):
                    process.kill()

        # Wait for process to end to ensure that
        # `process.returncode` is not None
        process.wait()

        if raise_exc and process.returncode != 0:
            raise EnvironmentError("\n >> " + "\n >> ".join(output))
        return process.returncode, output

    raise EnvironmentError(
        "Starting process of command '{}' failed".format(cmd)
    )


def get_path(path):
    """
    Extract path from remote path string

    example:
    user@host:/foo/bar/bar --> /foo/bar/baz
    """
    return path.split(":")[1] if ":" in path else path


def get_host(path):
    """
    Extract host from remote path string

    example:
    user@host:/foo/bar/bar --> user@host
    """
    return path.split(":")[0] if ":" in path else None


def cmd_remote(host, cmd):
    """
    Add ssh connection command to command `cmd`
    """
    return "ssh {} -q {} \"{}\"".format(
        " -i {}".format(ssh_key) if ssh_key else "",
        host, cmd
    ) if host else cmd


def eq_dir(path1, path2):
    """
    Check if `path1` and `path2` are equal
    """
    if ":" in path1 and ":" not in path2 or ":" not in path1 and ":" in path2:
        return False
    if ":" in path1 and ":" in path2:
        host,path1 = path1.split(":")[:2]
        host,path2 = path2.split(":")[:2]
    return os.path.realpath(path1) == os.path.realpath(path2)


def is_subdir(path, path_parent):
    """
    Check if `path` is subdirectory of `path_parent`
    """
    if ":" in path and ":" in path_parent:
        host,path = path.split(":")[:2]
        host,path_parent = path_parent.split(":")[:2]
    path = os.path.normpath(path)
    path_parent = os.path.normpath(path_parent)+"/"
    return path.startswith(path_parent)


def hardlink_dir(src_path, dest_path):
    """
    Clone directory tree `src_path` to `dest_path` by creating hardlinks to all
    files under `src_path`

    rsync is used to clone the directory structure to preserve symlinks. A
    cloning via "cp -rlp src_path dest_path" would not work.
    """
    host = get_host(src_path)
    src_path = get_path(src_path)
    dest_path = get_path(dest_path)
    cmd = "rsync -rlptgoDEAXWSH --delete "
    cmd +="--link-dest=\"{}/\" \"{}/\" \"{}/\"".format(
        src_path, src_path, dest_path
    )
    cmd = cmd_remote(host, cmd)
    shell_cmd(cmd, raise_exc=True)


def check_dir(path, mode="r"):
    """
    Check if directory `path` exists and is readable/writeable
    """
    host = get_host(path)
    path = get_path(path)
    cmd = "[[ -d \"{}\" && -{} \"{}\" ]] && echo 1 || echo 0".format(
        path, mode, path)
    cmd = cmd_remote(host, cmd)
    return shell_cmd(cmd, raise_exc=True)[1] == ["1"]


def rm_dir(path):
    """
    Remove directory `path`
    """
    host = get_host(path)
    path = get_path(path)
    cmd = "rm -rf \"{}\"".format(path)
    cmd = cmd_remote(host, cmd)
    shell_cmd(cmd, raise_exc=True)


def mv_dir(src_path, dest_path):
    """
    Move directory from `src_path` to `dest_path`
    """
    host = get_host(src_path)
    src_path = get_path(src_path)
    dest_path = get_path(dest_path)
    cmd = "mv \"{}\" \"{}\"".format(src_path, dest_path)
    cmd = cmd_remote(host, cmd)
    shell_cmd(cmd, raise_exc=True)


def get_backups(path, sort="asc"):
    """
    Return all backups inside `path`. Valid backups are all folders matching
    `backup_regex`
    """
    host = get_host(path)
    path = get_path(path)
    cmd = "cd \"{}\" ".format(path)
    cmd += "&& find . -maxdepth 1 -mindepth 1 -type d | tr -d \"./\""
    cmd = cmd_remote(host, cmd)
    ret,output=shell_cmd(cmd, raise_exc=True)
    backups = []
    for f in sorted(output, reverse=(sort == "desc")):
        if(re.match(backup_regex, f) != None):
            backups.append(
                Backup(datetime.datetime.strptime(f, date_fmt))
            )
    return backups


def new_backup_name():
    """
    Create new backup name according to current date/time
    """
    return datetime.datetime.today().strftime(date_fmt)


def fmt_backup_list(backups, msg=False):
    """
    Return list of backups as formatted string
    """
    ret = []
    for b in backups:
        ret.append("  {}{}".format(
            b.as_str(),
            " <- {}".format(b.msg) if msg else ""
        ))
    return "\n".join(ret)


def new_tmp_src(mv_record_path, src_path):
    """
    Generate new temporary name for source folder
    """
    name = "{}.tmp".format(random.randint(10000000,99999999))

    # ensure there is no file/folder with this name in the directory
    # `mv_record_path` and dirname(`src_path`)
    while check_dir(os.path.join(mv_record_path, name)) or \
            check_dir(os.path.join(os.path.dirname(src_path), name)):
        name = "{}.tmp".format(random.randint(10000000,99999999))
    return name


def quote_remote_path(path):
    """
    Quote whitespaces for remote path (needed for rsync command)
    """
    return path.replace(" ", "\\ ") if ":" in path else path


def rsync_cb(line):
    """
    This callback is called for every line of the rsync process output
    """
    log = logging.getLogger("worpbak")
    log.debug(" (rsync) {}".format(line))

    # cancel rsync if errors occur (marked by lines starting with "rsync:")
    return (not line.startswith("rsync:"))


def backup(src_path, dest_path, mv_record_path=None, dest_last_path=None,
        dry_run=False, rsync_args="", verbose=False):
    """
    Perform backup with the rsync command

    src_path : path to source directory
    dest_path : path to destination directory
    mv_record_path : path to mv-record
    dest_last_path : path to last backup destination
    dry_run : whether to simulate rsync (True) or not (False)
    rsync_args : additional rsync arguments
    verbose : log rsync output (True) or not (False)

    returns changed
        changed : only in dry_run mode: True if files have changed or False


    Backup strategy

    1. if previous backup exists (`dest_last_path`) create hardlink named
       `dest_path`.tmp, which serves as temporary destination (`dest_tmp_path`)

    if mv-record exists:

        2. create temporary source directory (`src_tmp_path`) as hardlink to
           source directory named as `src_path`.tmp

        3. run rsync from `mv_record_path` AND `src_tmp_path` SIMULTANEOUSLY to
           the temporary destination `dest_tmp_path`
           --> file/folder structure in `mv_record_path` and `dest_tmp_path` is
               the same
           --> rsync collects files to copy from `mv_record_path` and
               `src_tmp_path` simultaneously
           --> files in `src_tmp_path` which are moved or renamed but still
               hardlinked to files in `mv_record_path` are not copied but
               directly hardlinked to files from previous backups
           --> this results in a subfolder named `src_tmp` inside
               `dest_tmp_path` with the new file/folder structure but files are
               hardlinked to existing files, depite file movements or renames

        4. move temporary destination named `dest_tmp_path`/`src_tmp` to final
           destination `dest_path`

        5. remove temporary folders `src_tmp_path` and `dest_tmp_path`

    if no mv-record exists

        2. run rsync from `src_path` to `dest_tmp_path`

        3. rename `dest_tmp_path` to `dest_path`

        4. remove temporary folder `src_tmp_path`


    Reasons for temporary destination and source
        destination : prevent invalid backups. only if rsnyc runs successfully
                      tmp folder is copied to final destination
        src : the source folder is copied inside the mv-record on destination.
              this may cause a problem if there exists already a folder with the
              same name. therefore a new random temporary source folder is used
    """
    log = logging.getLogger("worpbak")

    # remove trailing slashes from paths
    src_path = src_path.rstrip("/")
    dest_path = dest_path.rstrip("/")
    if mv_record_path:
        mv_record_path = mv_record_path.rstrip("/")
    if dest_last_path:
        dest_last_path = dest_last_path.rstrip("/")

    # rsync command options:
    # -r : recurse into directories
    # -l : copy symlinks as symlinks
    # -p : preserve permissions
    # -t : preserve modification times
    # -g : preserve group
    # -o : preserve owner
    # -D : preserve device files/preserve special files
    # -E : preserve executability
    # -A : preserve ACLs
    # -X : preserve extended attributes
    # -W : copy whole file
    # -S : handle sparse files
    # -H : preserve hardlinks
    # -v : increase verbosity
    # -n : dry-run
    # -q : quiet (only errors are printed)
    # --no-inc-recursive : prevent rsync from collecting files recursively
    # --delete : delete extraneous files from destination dirs
    # --stats : show statistics at end of run
    cmd = "rsync -rlptgoDEAXWSHv --delete --no-inc-recursive " + rsync_args
    cmd += "{}".format(
        "-e \"ssh -i '{}'\"".format(ssh_key) if ssh_key else ""
    )
    if dry_run:
        cmd += " -n --stats"

        # disable mv-record in the case of the dry run to get the correct
        # amount of created/deleted files
        mv_record_path = None
    elif not verbose:
        cmd += " -q"

    # temporary destination directory
    dest_tmp_path = "{}.tmp".format(dest_path)
    if dest_last_path:
        # hardlink tmp destination to last backup
        hardlink_dir(dest_last_path, dest_tmp_path)

    ret = 0
    output = []

    # check if mv-record exists
    if mv_record_path and dest_last_path:

        # create tmp source directory
        src_tmp = new_tmp_src(mv_record_path, src_path)
        src_tmp_path = os.path.join(os.path.dirname(src_path), src_tmp)
        hardlink_dir(src_path, src_tmp_path)

        # run rsync
        cmd += " \"{}/\" \"{}\" \"{}/\"".format(
            quote_remote_path(mv_record_path),
            quote_remote_path(src_tmp_path.rstrip("/")),
            quote_remote_path(dest_tmp_path)
        )
        log.info(" $ {}".format(cmd))
        try:
            ret,output = shell_cmd(cmd, rsync_cb, raise_exc=True)

            # move tmp destination to final destination
            mv_dir(os.path.join(dest_tmp_path, src_tmp), dest_path)
        except Exception as e:
            rm_dir(dest_tmp_path) # clean up tmp folders
            rm_dir(src_tmp_path) # clean up tmp folders
            raise

        # remove temporary src and dest folders
        rm_dir(dest_tmp_path)
        rm_dir(src_tmp_path)

    # mv-record does not exist
    else:

        # run rsync
        cmd += " \"{}/\" \"{}/\"".format(
            quote_remote_path(src_path),
            quote_remote_path(dest_tmp_path)
        )
        log.info(" $ {}".format(cmd))

        try:
            ret,output = shell_cmd(cmd, rsync_cb, raise_exc=True)

            if not dry_run:
                # move tmp destination to final destination
                mv_dir(dest_tmp_path, dest_path)
            else:
                # remove tmp destination folder
                rm_dir(dest_tmp_path)

        except Exception as e:
            rm_dir(dest_tmp_path) # clean up
            raise


    if dry_run:
        # parse output to determine if src has changed. Look for lines
        # "Number of created files:"
        # "Number of deleted files:"
        changed = False
        for line in reversed(output):
            if line.startswith("Number of created files:") or \
                    line.startswith("Number of deleted files:") or \
                    line.startswith("Number of regular files transferred:"):
                no = int(
                    line.split(":")[1].split("(")[0].strip().replace(",", ""))
                if no != 0:
                    changed = True
                    break
        return changed


def clean(path, intervals, dry_run=False, backups=None):
    """
    Clean backups based on interval rules

    path : path to storage directory containing backups
    intervals : list of interval rules
    dry_run : only simulate clean
    backups : if not None use this list of backups

    return list of marked backups
    """
    log = logging.getLogger("worpbak")
    intervals.sort(key=lambda x: x.size)

    # get all backups sorted descending
    # -> backups[-1] = first backup
    # -> backups[0] = last backup
    if not backups:
        backups = get_backups(path, "desc")
    for backup in backups:
        backup.remove = True
        backup.msg = "REMOVE"

    for interval in intervals:
        cur_date = backups[0].date # date counter for this interval
        bak_cnt = 0 # backup counter for this interval

        # loop until date of first backup is reached or the number of backups
        # for this interval exceeds the maximum number
        # only backups which are not already kept based on a different interval
        # are counting for this interval
        while cur_date >= backups[-1].date and bak_cnt < interval.maxn:
            for backup in backups:

                # skip backup already marked for keeping
                if not backup.remove:
                    continue

                # check if backup.date is within the interval boundary starting
                # from cur_date backwards in time
                if interval.in_boundary(cur_date, backup.date):
                    backup.remove = False
                    backup.msg = "keep by {}. {}" .format(bak_cnt+1,
                        interval.__class__.__name__)
                    bak_cnt += 1
                    break

            # decrease `cur_date` not until backup list is looped totally
            cur_date = interval.lower_boundary(cur_date)

    # show result
    log.info(fmt_backup_list(backups, True))

    # remove backups
    if not dry_run:
        for backup in backups:
            if backup.remove:
                rm_dir(os.path.join(path, backup.as_str()))

    return backups
