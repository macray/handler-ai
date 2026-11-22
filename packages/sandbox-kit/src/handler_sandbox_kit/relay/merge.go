package main

// handler-relay merge UPPER CACHE [UPPER CACHE…]: an ended sandbox's additions to its caches, in
// a VM of their own started by its launcher as the user, with only that sandbox's disk and its
// caches mounted. UPPER is what the sandbox wrote over a cache (an overlay's upper folder; none
// when it never ran: nothing to add); CACHE the shared cache. Only new names are added: a name the cache has (the sandbox changed that file, or
// another sandbox added it since) is kept as it is, deletions are dropped. Each file is written
// under a temporary name in its folder, then hard-linked to its name, which fails if the name
// exists: nothing is replaced, and two merges at once need no lock. Every folder of CACHE is
// opened from its parent without following a link, so nothing is written outside CACHE whatever
// links the sandbox wrote; a link is added as a link, never followed.

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

type mergeCount struct{ added, bytes, kept, dropped int64 }

func mergeMain(args []string) {
	if len(args) == 0 || len(args)%2 != 0 {
		fail("usage: handler-relay merge UPPER CACHE [UPPER CACHE…]")
	}
	failed := false
	for i := 0; i < len(args); i += 2 { // each cache whatever another's merge did
		if err := mergeOne(args[i], args[i+1]); err != nil {
			fmt.Fprintf(os.Stderr, "handler-relay: merge into %s: %v\n", args[i+1], err)
			failed = true
		}
	}
	if failed {
		os.Exit(125)
	}
	os.Exit(0)
}

func mergeOne(upper, cachePath string) error {
	if _, err := os.Lstat(upper); errors.Is(err, os.ErrNotExist) {
		return nil // the sandbox never wrote there
	}
	cache, err := syscall.Open(cachePath, syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if err != nil {
		return err
	}
	defer syscall.Close(cache)
	var n mergeCount
	err = mergeDir(upper, cache, &n)
	fmt.Printf("merged into %s: %d added (%d bytes), %d kept as they were, %d dropped\n",
		cachePath, n.added, n.bytes, n.kept, n.dropped)
	return err
}

// mergeDir adds what the folder upper holds to the folder of the cache open as dir.
func mergeDir(upper string, dir int, n *mergeCount) error {
	entries, err := os.ReadDir(upper)
	if err != nil {
		return err
	}
	for _, e := range entries {
		name := e.Name()
		src := filepath.Join(upper, name)
		info, err := os.Lstat(src)
		if err != nil {
			return err
		}
		mode := info.Mode()
		switch {
		case strings.HasPrefix(name, ".wh."), isWhiteout(info): // a deletion: dropped
			n.dropped++
		case mode.IsDir():
			sub, err := openDir(dir, name, true)
			if errors.Is(err, syscall.ENOTDIR) || errors.Is(err, syscall.ELOOP) {
				n.kept++ // the cache has that name, not as a folder: kept, nothing under it added
				continue
			}
			if err != nil {
				return fmt.Errorf("%s: %w", src, err)
			}
			err = mergeDir(src, sub, n)
			syscall.Close(sub)
			if err != nil {
				return err
			}
		case mode.IsRegular() || mode&os.ModeSymlink != 0:
			added, err := addEntry(src, info, dir, name)
			if err != nil {
				return fmt.Errorf("%s: %w", src, err)
			}
			if added {
				n.added++
				n.bytes += info.Size()
			} else {
				n.kept++
			}
		default: // a device, a pipe, a socket: not a cache's
			n.dropped++
		}
	}
	return nil
}

// isWhiteout: the kernel's and fuse-overlayfs's mark of a deleted file, a 0:0 character device.
func isWhiteout(info os.FileInfo) bool {
	st, ok := info.Sys().(*syscall.Stat_t)
	return ok && info.Mode()&os.ModeCharDevice != 0 && st.Rdev == 0
}

// openDir opens the folder name of dir, never through a link; made when missing and make.
func openDir(dir int, name string, make bool) (int, error) {
	flags := syscall.O_RDONLY | syscall.O_DIRECTORY | syscall.O_NOFOLLOW | syscall.O_CLOEXEC
	fd, err := syscall.Openat(dir, name, flags, 0)
	if errors.Is(err, syscall.ENOENT) && make {
		if err := syscall.Mkdirat(dir, name, 0o755); err != nil && !errors.Is(err, syscall.EEXIST) {
			return -1, err
		}
		fd, err = syscall.Openat(dir, name, flags, 0)
	}
	return fd, err
}

// addEntry adds the file or link src under name in dir unless name exists there: false then.
func addEntry(src string, info os.FileInfo, dir int, name string) (bool, error) {
	var st syscall.Stat_t
	if err := fstatat(dir, name, &st); err == nil {
		return false, nil
	} else if !errors.Is(err, syscall.ENOENT) {
		return false, err
	}
	tmp := fmt.Sprintf(".handler-merge-%d-%s", os.Getpid(), name)
	if len(tmp) > 255 {
		tmp = fmt.Sprintf(".handler-merge-%d", os.Getpid())
	}
	if info.Mode()&os.ModeSymlink != 0 {
		target, err := os.Readlink(src)
		if err != nil {
			return false, err
		}
		if err := symlinkat(target, dir, tmp); err != nil {
			return false, err
		}
	} else if err := copyInto(src, dir, tmp, uint32(info.Mode().Perm())); err != nil {
		syscall.Unlinkat(dir, tmp)
		return false, err
	}
	err := linkat(dir, tmp, dir, name)
	syscall.Unlinkat(dir, tmp)
	if errors.Is(err, syscall.EEXIST) { // added meanwhile by another merge
		return false, nil
	}
	return err == nil, err
}

// copyInto writes src's bytes to a new file name of dir, with mode.
func copyInto(src string, dir int, name string, mode uint32) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	flags := syscall.O_WRONLY | syscall.O_CREAT | syscall.O_EXCL | syscall.O_NOFOLLOW | syscall.O_CLOEXEC
	fd, err := syscall.Openat(dir, name, flags, mode)
	if err != nil {
		return err
	}
	out := os.NewFile(uintptr(fd), name)
	_, err = io.Copy(out, in)
	if cerr := out.Close(); err == nil {
		err = cerr
	}
	if err == nil {
		err = syscall.Fchmodat(dir, name, mode, 0) // whatever the umask took
	}
	return err
}

const atSymlinkNofollow = 0x100 // AT_SYMLINK_NOFOLLOW

func fstatat(dir int, name string, st *syscall.Stat_t) error {
	return syscall.Fstatat(dir, name, st, atSymlinkNofollow)
}

func linkat(olddir int, oldname string, newdir int, newname string) error {
	old, err := syscall.BytePtrFromString(oldname)
	if err != nil {
		return err
	}
	new, err := syscall.BytePtrFromString(newname)
	if err != nil {
		return err
	}
	// flags 0: a link is linked itself, never followed
	_, _, e := syscall.Syscall6(syscall.SYS_LINKAT, uintptr(olddir), uintptr(unsafe.Pointer(old)),
		uintptr(newdir), uintptr(unsafe.Pointer(new)), 0, 0)
	if e != 0 {
		return e
	}
	return nil
}

func symlinkat(target string, dir int, name string) error {
	t, err := syscall.BytePtrFromString(target)
	if err != nil {
		return err
	}
	n, err := syscall.BytePtrFromString(name)
	if err != nil {
		return err
	}
	_, _, e := syscall.Syscall(syscall.SYS_SYMLINKAT, uintptr(unsafe.Pointer(t)), uintptr(dir),
		uintptr(unsafe.Pointer(n)))
	if e != 0 {
		return e
	}
	return nil
}
