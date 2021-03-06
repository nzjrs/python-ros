import sys
import glob
import shutil
import os.path
import filecmp
import distutils.dir_util
import distutils.file_util

import roslib.packages
import roslib.manifest

IGNORES = (".pyc",".cpp",".c",".png",".h")

def _glob_dirs(root, recursive=False):
    if recursive:
        return [os.path.join(_root,_d) for _root,_dirnames,_filenames in os.walk(root) for _d in _dirnames]
    else:
        return [i for i in glob.glob(os.path.join(root,"*")) if os.path.isdir(i)]

def _remove_empty_folders(path, removed=[]):
    if not os.path.isdir(path):
        return

    # remove empty subfolders
    files = os.listdir(path)
    if len(files):
        for f in files:
            fullpath = os.path.join(path, f)
            if os.path.isdir(fullpath):
                _remove_empty_folders(fullpath, removed)

    # if folder empty, delete it
    files = os.listdir(path)
    if len(files) == 0:
        removed.append(path)
        os.rmdir(path)

    return removed

def _copy_recursively(src, dest, ignore=IGNORES):
    if os.path.isdir(src):
        #print "cdir", src, dest
        copied = distutils.dir_util.copy_tree(src, dest)
        #remove files we should ignore
        for c in copied:
            if os.path.isfile(c):
                if c.endswith(ignore):
                    os.remove(c)
        #remove any hanging directories
        _remove_empty_folders(dest)
    elif os.path.isfile(src):
        #print "cf", src, dest
        if not os.path.isdir(dest):
            os.makedirs(dest)
        shutil.copy2(src,dest)
    else:
        raise Exception("Copy not supported")


def _copy_pkg_data(p, rel, ddir,required=True):
    src = os.path.join(roslib.packages.get_pkg_dir(p, required=required),rel)
    if os.path.exists(src):
        if os.path.isfile(src):
            dest = os.path.join(ddir,p)
        elif os.path.isdir(src):
            dest = os.path.join(ddir,p,rel)
        _copy_recursively(src, dest)

def _import_and_copy(p, odir):
    mod = __import__(p)
    fn = mod.__file__
    if os.path.basename(fn).startswith("__init__"):
        src = roslib.packages.get_pkg_dir(p, required=False)

        if src is None:
            srcs = [os.path.dirname(fn)]
            outs = [os.path.join(odir,p)]
        else:
            srcs = _glob_dirs(os.path.join(src,"src"))
            outs = [os.path.join(odir,os.path.basename(i)) for i in _glob_dirs(os.path.join(src,"src"))]

        for src,out in zip(srcs,outs):
            _copy_recursively(src,out)

    elif os.path.isfile(fn) and fn.endswith(".pyc"):
        #this is just a file, not a module. copy the py (not pyc) file
        shutil.copy2(fn[0:-1],odir)

    return fn

def _copy_executables(p, bdir):
    for f in os.listdir(p):
        path = os.path.join(p,f)
        #executable
        if os.access(path, os.X_OK) and os.path.isfile(path):
            with open(path,'r') as exe:
                for line in exe:
                    if "python" in line:
                        shutil.copy2(path,os.path.join(bdir,f))
                    break

def _import_roslaunch(srcdir,bindir,ddir):
    import_packages(srcdir,bindir,ddir,"rosmaster","roslaunch")
    _copy_pkg_data("roslaunch","roscore.xml",ddir)

    #FIXME: rewrite roscore here...

def _import_roslib(srcdir,bindir,ddir):
    _import_and_copy("ros",srcdir)
    _import_and_copy("roslib",srcdir)
    #rewrite roslib to make load_manifest a noop and to set some env variables

    #FIXME: use setuptools to get the installation /bin path and datadir
    contents = """
import os.path
import tempfile

DDIR = os.path.expanduser('~/Programming/python-ros/data/')

os.environ['ROS_PACKAGE_PATH'] = tempfile.mkdtemp()
os.environ['ROS_ROOT'] = os.environ.get('ROS_ROOT','/usr/local')
os.environ['ROS_BUILD'] = os.environ['ROS_ROOT']
os.environ['ROS_MASTER_URI'] = os.environ.get('ROS_MASTER_URI','http://localhost:11311')

from roslib.scriptutil import is_interactive, set_interactive
import roslib.stacks

#from roslib.launcher import load_manifest
def load_manifest(*args):
    pass

def _get_pkg_dir(package, required=True, ros_root=None, ros_package_path=None):
    p = os.path.join(DDIR,package)
    print "monkey patched get_pkg/stack_dir",package,"=",p
    return p

import roslib.packages
roslib.packages.get_pkg_dir = _get_pkg_dir

def _get_stack_dir(stack, env=None):
    return _get_pkg_dir(stack)

roslib.stacks.get_stack_dir = _get_stack_dir

import roslib.manifest
def _manifest_file_by_dir(package_dir, required=True, env=None):
    print "monkey patching manifest for", package_dir
    tdir = tempfile.mkdtemp()
    dest = os.path.join(tdir,'manifest.xml')
    with open(dest,'w') as f:
        f.write('<package></package>')
    return dest
roslib.manifest._manifest_file_by_dir = _manifest_file_by_dir

"""
    with open(os.path.join(srcdir,'roslib','__init__.py'),'w') as f:
        f.write(contents)

def _import_ros_binaries(bdir):
    rosroot = os.environ['ROS_ROOT']
    _copy_executables(os.path.join(rosroot,"bin"), bdir)

def import_msgs(srcdir,bindir,ddir,*pkgs):
    for p in pkgs:
        import_packages(srcdir,bindir,ddir,p)
        _copy_pkg_data(p, "msg", ddir)

def import_srvs(srcdir,bindir,ddir,*pkgs):
    for p in pkgs:
        import_packages(srcdir,bindir,ddir,p)
        _copy_pkg_data(p, "srv", ddir)

def import_packages(srcdir,bindir,ddir,*pkgs):
    for p in pkgs:
        roslib.load_manifest(p)
        try:
            fn = _import_and_copy(p, srcdir)
        except ImportError:
            pass

        #base  = os.path.abspath(roslib.packages.get_pkg_dir(p, required=True))
        _copy_pkg_data(p, "manifest.xml", ddir)

        for _bin in ("bin","scripts","nodes"):
            _bindir = os.path.join(roslib.packages.get_pkg_dir(p, required=True),_bin)
            if os.path.isdir(_bindir):
                _copy_executables(_bindir, bindir)

def import_ros_core(working_dir, *pkgs):

    srcdir = os.path.join(working_dir,"src")
    bindir = os.path.join(working_dir,"bin")
    datadir = os.path.join(working_dir,"data")

    for d in (srcdir,bindir,datadir):
        if os.path.exists(d):
            shutil.rmtree(d)
        os.mkdir(d)

    _import_roslib(srcdir,bindir,datadir)
    _import_roslaunch(srcdir,bindir,datadir)
    _import_ros_binaries(bindir)

    assert type(pkgs) == tuple

    all_srvs = ["std_srvs"] + list(pkgs)
    all_msgs = ["std_msgs","geometry_msgs","rosgraph_msgs"] + list(pkgs)
    all_pkgs = ["rosgraph","rostopic","rosnode","rospy","rosbag"] + list(pkgs)

    import_srvs(srcdir,bindir,datadir,*all_srvs)
    import_msgs(srcdir,bindir,datadir,*all_msgs)
    import_packages(srcdir,bindir,datadir,*all_pkgs)

    return srcdir,bindir,datadir

def import_ros_package(srcdir, bindir, datadir, pkg, data=None, deps=True):
    if deps:
        pkgs = [pkg] + roslib.manifest.load_manifest(pkg).depends
    else:
        pkgs = [pkg]

    for p in pkgs:
        #ensure not unicode...
        p = str(p)

        for d in (roslib.packages.MSG_DIR, roslib.packages.SRV_DIR):
            try:
                _copy_pkg_data(p,d,datadir,required=True)
            except roslib.packages.InvalidROSPkgException:
                pass

        import_packages(srcdir,bindir,datadir,p)

    if data:
        _copy_pkg_data(pkg,data,datadir,required=True)

def get_disutils_cmds(srcdir, bindir, datadir):
    kwargs = {
        "packages":[],
        "py_modules":[],
        "package_data":{},
    }

    for f in glob.glob(os.path.join(srcdir,"*.py")):
        fn = os.path.basename(f)
        kwargs["py_modules"].append(os.path.splitext(fn)[0])
    
    for f in _glob_dirs(srcdir, recursive=True):
        relf = f.replace(srcdir,'')
        if relf[0] == '/': relf = relf[1:]
        #create a package name 
        pn = ".".join(relf.split('/'))
        kwargs["packages"].append(pn)

    for f in _glob_dirs(datadir, recursive=False):
        #only ship data for packages that we are shipping the source too
        fn = os.path.basename(f)
        if fn in kwargs["packages"]:
            #distutils requires a package relative datapath because distutils
            pkgdd = os.path.join(datadir,fn)
            pkgreldd = os.path.relpath(pkgdd,os.path.join(srcdir,fn))
            if os.path.isdir(pkgdd):
                kwargs["package_data"][fn] = [
                    os.path.join(pkgreldd,"manifest.xml"),
                    os.path.join(pkgreldd,"msg","*.msg"),
                    os.path.join(pkgreldd,"srv","*.srv"),
                ]

    kwargs["scripts"] = [f for f in glob.glob(os.path.join(bindir,"*")) if os.path.isfile(f)]
    
    kwargs["package_dir"] = {'': 'src'}

    return kwargs

if __name__ == "__main__":
    import tempfile
    tdir = tempfile.mkdtemp()
    import_ros_core(tdir)
    print "package data in", tdir

