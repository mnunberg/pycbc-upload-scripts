#!/usr/bin/env python
from distutils.dist import Distribution
from distutils.command.upload import upload
from argparse import ArgumentParser, REMAINDER
from ConfigParser import RawConfigParser
from urllib2 import urlopen
from threading import Thread
import os.path

from cbdist import CouchbaseRelease, DistFile

ap = ArgumentParser()
ap.add_argument('files',
                nargs=REMAINDER,
                help="Files to upload (paths or URLs)")

ap.add_argument('-i', '--file-list',
                help='Specify a list from which to read file names')

ap.add_argument('-c',
                '--config',
                default='pypi-upload.cfg',
                help="Configuration file to use")

ap.add_argument('-D', '--define',
                action='append',
                default=[],
                metavar='section.option=value',
                help="Define extra options for section")

opts = ap.parse_args()
config = RawConfigParser()

try:
    with open(opts.config, "r") as conf_fp:
        config.read(opts.config)

except IOError as e:
    print e


for defined in opts.define:
    section, kv = defined.split('.', 2)
    kv = kv.split('=')
    try:
        k, v = kv
    except ValueError:
        k = kv[0]
        v = True
    config.set(section, k, v)

for cred in ('username', 'password'):
    if not config.has_option('pypi', cred):
        config.set('pypi', cred, raw_input(cred + ': '))

# Generate the dist list
dists = []
flist = opts.files
if opts.file_list:
    [flist.append(x.rstrip()) for x in open(opts.file_list).readlines()]

flist = [x for x in flist if x]

for f in flist:
    if f.startswith("http://"):
        dist = DistFile.from_uri(f)
    elif os.path.exists(f):
        dist = DistFile.from_local_file(f)
    else:
        dist = DistFile(f)

    dists.append(dist)


def process_dist(dist):
    if dist.suffix == "zip":
        return

    d = {}
    for k in config.options('dist'):
        d[k] = config.get('dist', k)


    d['version'] = dist.cbrel.relvers

    print "Release:", dist.cbrel.relvers

    if d['classifiers']:
        d['classifiers'] = [x for x in d['classifiers'].split('\n') if x]

    c = upload(Distribution(d))
    c.repository = config.get('pypi', 'repository')
    c.username = config.get('pypi', 'username')
    c.password = config.get('pypi', 'password')

    if dist.already_uploaded(c.repository):
        print "Already uploaded.."
        return

    dist.prepare_upload()
    c.upload_file('bdist_wininst', dist.cbrel.pyvers, dist.symlink)

thrs = [Thread(target=process_dist, args=(d,)) for d in dists]
[t.start() for t in thrs]
[t.join() for t in thrs]
