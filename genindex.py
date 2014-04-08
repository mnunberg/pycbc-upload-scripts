#!/usr/bin/env python
import os
import os.path
import sys
import cgi
import re
import argparse
from subprocess import Popen, PIPE
from cbdist import CouchbaseRelease, S3Index
from threading import Thread

# This actually contains only the releases *before* the last release
RELEASED_VERSIONS = (
    '1.0.0-beta',
    '1.0.0',
)

ap = argparse.ArgumentParser()
ap.add_argument('--update', action='store_true', help="Re-fetch listings")
ap.add_argument('--upload', action='store_true', help="Upload this page to S3")
ap.add_argument('--modacl', action='store_true', help="Modify ACLs")

opts = ap.parse_args()
s3index = S3Index(opts.update)

fp = open("index.html", "w")
fp.write('''
<html>
    <body>
        <table border="1" cellpadding="5">
            <thead>
                <tr>
                <th>Release</th>
                <th>Arch</th>
                <th>Python Version</th>
                <th>File</th>
            </tr>
        </thead>
''')

if opts.modacl:
    thrs = [Thread(target=d.make_public) for d in s3index.dists]
    [t.start() for t in thrs]
    [t.join() for t in thrs]

for dist in s3index.dists:
    if dist.suffix == 'zip':
        continue

    do_skip = False

    try:
        cbrel = dist.cbrel
    except Exception as e:
        print e
        continue

    if cbrel.v_minor == 0 and cbrel.commit_count != 0:
        do_skip = True

    if do_skip:
        with open("stale.txt", "a") as rej:
            rej.write(dist.s3uri + "\n")

    fmtstr = '''
    <tr>
        <td>{release}</td>
        <td>{arch}</td>
        <td>{pyvers}</td>
        <td><a href="{fname_url}">{fname}</a></td>
    </tr>
    '''
    html = fmtstr.format(release=cbrel.relvers,
                         arch=cbrel.arch,
                         fname_url=dist.httpuri,
                         fname=dist.basename,
                         pyvers=cbrel.pyvers)
    fp.write(html)


fp.write('</table></body></html>\n')
fp.close()

if opts.upload:
    os.system("s3cmd put index.html s3://{ub} -P".format(
        ub=CouchbaseRelease.S3_ROOT))
