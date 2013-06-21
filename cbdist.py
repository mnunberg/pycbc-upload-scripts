import re
import os
import os.path
import json
from urllib2 import Request, urlopen, HTTPError
from subprocess import Popen, PIPE


class HeadRequest(Request):
    def get_method(self):
        return "HEAD"

class CouchbaseRelease(object):
    S3_ROOT = "packages.couchbase.com/clients/python/snapshots"
    CACHE = 'distcache'

    def __init__(self, infofile):
        js = json.load(open(infofile, "rb"))
        self.js = js
        self.build_date = js['build_time']

        restr = "couchbase-(.+)\.(win32|win-amd64)-py(\d.\d).*"
        orig_dist = js['dist_file']
        match = re.match(restr, orig_dist)
        self.relvers, self.arch, self.pyvers = match.groups()
        self.gitvers = js['git_version']
        self.orig_dist = orig_dist

    @classmethod
    def from_distfile(cls, name, cache=CACHE):
        bname = os.path.basename(name)
        infofile = os.path.join(cache, bname) + ".info"

        if not os.path.exists(infofile):
            infourl = "http://" + cls.S3_ROOT + '/' + os.path.basename(infofile)
            print "Fetching", infourl

            uo = urlopen(infourl)

            fp = open(infofile, "wb")
            fp.write(uo.read())
            fp.close()
        else:
            print infofile, "already exists.."

        return cls(infofile)

class DistFile(object):

    def __init__(self, uqpath, cache=CouchbaseRelease.CACHE):
        self.path = uqpath
        self._cbrel = None
        self._cache = cache

    @classmethod
    def from_local_file(cls, localpath):
        bpath = os.path.basename(localpath)
        bpath = CouchbaseRelease.S3_ROOT + '/' + bpath
        return cls(bpath)

    @classmethod
    def from_uri(cls, uri):
        uri = uri.replace("http://", "")
        return cls.from_local_file(uri)

    @property
    def cbrel(self):
        if not self._cbrel:
            self._cbrel = CouchbaseRelease.from_distfile(self.path,
                                                         cache=self._cache)
        return self._cbrel


    @property
    def suffix(self):
        return self.path.split('.')[-1]

    @property
    def s3uri(self):
        return "s3://" + self.path

    @property
    def httpuri(self):
        return "http://" + self.path

    @property
    def infouri(self):
        return self.httpuri + ".info"

    @property
    def symlink(self):
        return os.path.join(self._cache, 'symlinks', self._cbrel.orig_dist)

    @property
    def local_fullpath(self):
        return os.path.abspath(os.path.join(self._cache, self.basename))

    def already_uploaded(self, repo):
        rpath = repo.split('/')[:-1]
        components = [
            'packages',
            self.cbrel.pyvers,
            'c',
            'couchbase',
            self.cbrel.orig_dist
        ]
        components = rpath + components
        url = '/'.join(components)
        print url
        try:
            hreq = HeadRequest(url)
            uo = urlopen(hreq)
            return True
        except HTTPError as e:
            if e.code == 404:
                return False
            raise


    def download_dist(self):
        if os.path.exists(self.local_fullpath):
            return

        uo = urlopen(self.httpuri)
        fp = open(self.local_fullpath, "wb")
        while True:
            val = uo.read(8192)
            if not val:
                break
            fp.write(val)
        fp.close()

    def make_symlink(self):
        if os.path.exists(self.symlink):
            if not os.path.islink(self.symlink):
                raise Exception("Expected a symlink", self.symlink)
            if os.readlink(self.symlink) == self.local_fullpath:
                return

        print self.local_fullpath, ">", self.symlink

        os.symlink(self.local_fullpath, self.symlink)

    def prepare_upload(self):
        self.download_dist()
        self.make_symlink()

    @property
    def basename(self):
        return os.path.basename(self.path)

    def make_public(self):
        for url in (self.httpuri, self.infouri):
            try:
                response = urlopen(HeadRequest(url))
                print url, "Already public.."
            except HTTPError as e:
                if e.code == 403:
                    print url, "not public yet.. modifying"
                    rv = os.system("s3cmd setacl -P " + url.replace("http", "s3"))
                    assert rv == 0
                else:
                    raise

    def __str__(self):
        return self.path


class S3Index(object):
    DNAME = 's3info'
    LISTINGS = 'distlist'

    def __init__(self, force_update=False, cache=CouchbaseRelease.CACHE):
        self.cache = os.path.join(cache, self.DNAME)

        if not os.path.exists(self.cache):
            os.makedirs(self.cache)

        self.distlist = os.path.join(self.cache, self.LISTINGS)

        if not os.path.exists(self.distlist):
            force_update = True

        self.download_index(force_update)
        self.dists = [x.rstrip() for x in open(self.distlist, "r").readlines()]
        self.dists = [DistFile(x) for x in self.dists]

    def download_index(self, force=False):
        if os.path.exists(self.distlist) and not force:
            return

        po = Popen(("s3cmd", "ls", "-r", "s3://" + CouchbaseRelease.S3_ROOT),
                   stdout=PIPE)

        dists = []
        out, err = po.communicate()
        for line in out.split('\n'):
            line = line.rstrip()
            if not line:
                continue

            flds = line.split()
            mdate, mtime, fsize, path = flds
            path = path.replace('s3://', '')
            fname = os.path.basename(path)

            if fname.endswith('.info') or not fname.startswith('couchbase-'):
                continue

            dists.append(DistFile(path))

        fp = open(self.distlist, 'wb')
        for d in dists:
            print d.path
            fp.write(d.path + "\n")

        fp.close()
