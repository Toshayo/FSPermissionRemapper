import errno
import json
import os
import sys

# noinspection PyPackageRequirements
import fuse


class PermissionRemappedFilesystem(fuse.LoggingMixIn, fuse.Operations):
    REMAPPER_PERM_FILE = '.fs_perm_remapper.json'

    def __init__(self, path):
        self.src_path = path
        if os.path.exists(os.path.join(path, self.REMAPPER_PERM_FILE)):
            with open(os.path.join(path, self.REMAPPER_PERM_FILE)) as file:
                self.permissions = json.load(file)
        else:
            self.permissions = {}

    def get_src_path(self, path: str):
        return os.path.join(self.src_path, path[1:] if path[0] == '/' else path)

    def get_permissions(self, path):
        if path not in self.permissions:
            self.permissions[path] = {
                'uid': 0,
                'gid': 0,
                'mode': os.lstat(self.get_src_path(path)).st_mode
            }
        return self.permissions[path]

    def readdir(self, path, fh):
        real_path = self.get_src_path(path)
        entries = ['.', '..']
        if os.path.isdir(real_path):
            entries.extend(os.listdir(real_path))
        if path == '/':
            entries.remove(self.REMAPPER_PERM_FILE)
        for entry in entries:
            yield entry

    def getattr(self, path, fh=None):
        stats = os.lstat(self.get_src_path(path))
        perms = self.get_permissions(path)
        return {
            'st_mode': perms['mode'],
            'st_uid': perms['uid'],
            'st_gid': perms['gid'],

            'st_nlink': stats.st_nlink,
            'st_size': stats.st_size,
            'st_blocks': stats.st_blocks,
            'st_blksize': stats.st_blksize,
            'st_ino': stats.st_ino,
            'st_dev': stats.st_dev,

            'st_ctime': stats.st_ctime,
            'st_mtime': stats.st_mtime,
            'st_atime': stats.st_atime
        }

    def chown(self, path, uid, gid):
        if path not in self.permissions:
            mode = os.lstat(self.get_src_path(path)).st_mode
            self.permissions[path] = {
                'uid': uid,
                'gid': gid,
                'mode': mode
            }
        else:
            self.permissions[path]['uid'] = uid
            self.permissions[path]['gid'] = gid

    def chmod(self, path, mode):
        if path not in self.permissions:
            self.permissions[path] = {
                'uid': 0,
                'gid': 0,
                'mode': mode
            }
        else:
            self.permissions[path]['mode'] = mode

    def access(self, path, amode):
        if not os.access(self.get_src_path(path), amode):
            raise fuse.FuseOSError(errno.EACCES)

    def readlink(self, path):
        path = os.readlink(self.get_src_path(path))
        if path[0] == '/':
            # Remap to src root
            path = os.path.relpath(path, self.src_path)
        return path

    def mknod(self, path, mode, dev):
        print('MKNOD ' + path)
        return os.mknod(self.get_src_path(path), mode, dev)

    def rmdir(self, path):
        return os.rmdir(self.get_src_path(path))

    def mkdir(self, path, mode):
        print('MKDIR ' + path)
        return os.mkdir(self.get_src_path(path), mode)

    def statfs(self, path):
        stats = os.statvfs(self.get_src_path(path))
        return {
            'f_bavail': stats.f_bavail,
            'f_bfree': stats.f_bfree,
            'f_blocks': stats.f_blocks,
            'f_bsize': stats.f_bsize,
            'f_favail': stats.f_favail,
            'f_ffree': stats.f_ffree,
            'f_files': stats.f_files,
            'f_flag': stats.f_flag,
            'f_frsize': stats.f_frsize,
            'f_namemax': stats.f_namemax
        }

    def unlink(self, path):
        return os.unlink(self.get_src_path(path))

    def symlink(self, target, source):
        # TODO: verify
        print('Symlink: ' + target + ', ' + source)
        return os.symlink(self.get_src_path(target), self.get_src_path(source))

    def rename(self, old, new):
        return os.rename(self.get_src_path(old), self.get_src_path(new))

    def link(self, target, source):
        return os.link(self.get_src_path(target), self.get_src_path(source))

    def utimens(self, path, times=None):
        return os.utime(self.get_src_path(path), times)

    def open(self, path, flags):
        return os.open(self.get_src_path(path), flags)

    def create(self, path, mode, fi=None):
        print('Create ' + path)
        os.open(self.get_src_path(path), os.O_WRONLY | os.O_CREAT, mode)

    def read(self, path, size, offset, fh):
        os.lseek(fh, offset, os.SEEK_SET)
        return os.read(fh, size)

    def write(self, path, data, offset, fh):
        os.lseek(fh, offset, os.SEEK_SET)
        return os.write(fh, data)

    def truncate(self, path, length, fh=None):
        with open(self.get_src_path(path), 'r+') as f:
            f.truncate(length)

    def flush(self, path, fh):
        return os.fsync(fh)

    def release(self, path, fh):
        return os.close(fh)

    def fsync(self, path, datasync, fh):
        return os.fsync(fh)

    def init(self, root):
        print('FS mounted')

    def destroy(self, root):
        final_perms = {}
        for path, perms in self.permissions.items():
            stats = os.lstat(self.get_src_path(path))
            if stats.st_mode == perms['mode'] and perms['uid'] == 0 and perms['gid'] == 0:
                continue
            final_perms[path] = perms
        with open(os.path.join(self.src_path, self.REMAPPER_PERM_FILE), 'w') as file:
            json.dump(final_perms, file)
        print('FS unmounted')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Usage: ' + sys.argv[0] + ' SRC_FOLDER MOUNT_POINT')
        exit(1)
    if os.path.isdir(sys.argv[1]) and os.path.isdir(sys.argv[2]):
        fuse.FUSE(
            PermissionRemappedFilesystem(sys.argv[1]), sys.argv[2],
            foreground=True, allow_root=True
        )
    else:
        print('One of the folders does not exist!')
        exit(1)
