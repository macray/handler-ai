package main

// --nested DISK: what an engine inside the sandbox (rootless Podman or Docker) needs of the VM,
// set up as root before the relay becomes the user (contract A.5, Apple container's part):
//   - Apple's masks on /proc and /sys taken off: while parts of /proc are hidden or read-only,
//     the kernel refuses an inner container its own /proc;
//   - /etc/passwd naming the user (Podman finds the user's subordinate ids by its name),
//     /etc/subuid and /etc/subgid giving it 65536 ids: copies written on the disk, root's (the
//     user cannot change them), mounted over the image's;
//   - /dev/fuse and /dev/net/tun, the engine's storage and network, opened to the user;
//   - /tmp and /var/tmp on the disk, not in memory: the engine's state and its temporary copies
//     of images are there; and the disk's `engine` folder, the user's, for the engine's store.
// Then the bounding set keeps an engine's capabilities (engineCaps) and no_new_privs is not set:
// the engine's newuidmap and newgidmap need their file capabilities. The user has none of them
// otherwise; what loosens is in that sandbox's VM only.

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
)

// engineCaps: Podman's default capabilities, the bounding set of a nested sandbox (the
// capabilities a program may gain from its file, as newuidmap does; none is held).
var engineCaps = map[uintptr]bool{
	0: true, 1: true, 3: true, 4: true, 5: true, 6: true, 7: true, 8: true, // CHOWN DAC_OVERRIDE FOWNER FSETID KILL SETGID SETUID SETPCAP
	10: true, 18: true, 31: true, // NET_BIND_SERVICE SYS_CHROOT SETFCAP
}

// masks: what Apple's VMs hide or make read-only of /proc and /sys.
var masks = []string{
	"/proc/keys", "/proc/timer_list", "/proc/bus", "/proc/fs", "/proc/irq", "/proc/sys",
	"/sys/firmware",
}

// subordinate: the first of the user's subordinate ids, and how many.
const (
	subordinateFirst = 100000
	subordinateCount = 65536
)

func prepareNested(disk string, uid, gid int) {
	for _, m := range masks {
		if err := syscall.Unmount(m, 0); err != nil && !errors.Is(err, syscall.EINVAL) &&
			!errors.Is(err, syscall.ENOENT) {
			fail("nested: %s: %v", m, err)
		}
	}
	if uid >= subordinateFirst && uid < subordinateFirst+subordinateCount {
		fail("nested: uid %d is among the subordinate ids", uid)
	}
	etc := filepath.Join(disk, "etc")
	if err := os.MkdirAll(etc, 0o755); err != nil {
		fail("nested: %v", err)
	}
	ids := fmt.Sprintf("%d:%d:%d\n", uid, subordinateFirst, subordinateCount)
	given := map[string]string{"passwd": passwd(uid, gid), "subuid": ids, "subgid": ids}
	for _, name := range []string{"passwd", "subuid", "subgid"} {
		if _, err := os.Stat("/etc/" + name); errors.Is(err, os.ErrNotExist) && name != "passwd" {
			continue // an image without them has no rootless engine (its newuidmap's files)
		}
		path := filepath.Join(etc, name)
		if err := os.WriteFile(path, []byte(given[name]), 0o644); err != nil {
			fail("nested: %v", err)
		}
		bind(path, "/etc/"+name, 0)
	}
	engine := filepath.Join(disk, "engine") // the engine's store, the user's
	if err := os.MkdirAll(engine, 0o700); err != nil {
		fail("nested: %v", err)
	}
	if err := os.Chown(engine, uid, gid); err != nil {
		fail("nested: %v", err)
	}
	for _, dev := range []string{"/dev/fuse", "/dev/net/tun"} {
		if err := os.Chown(dev, uid, gid); err != nil {
			fail("nested: %s: %v", dev, err)
		}
	}
	for target, name := range map[string]string{"/tmp": "tmp", "/var/tmp": "var-tmp"} {
		folder := filepath.Join(disk, name)
		if err := os.MkdirAll(folder, 0o755); err != nil {
			fail("nested: %v", err)
		}
		if err := syscall.Chmod(folder, 0o1777); err != nil { // the sticky bit, as /tmp's
			fail("nested: %v", err)
		}
		bind(folder, target, syscall.MS_NOSUID|syscall.MS_NODEV)
	}
}

// composeRegistries writes DISK/etc/registries.conf: the image's registries.conf (its search
// registries; its drop-in folder, the short names, is read whatever the file), then the
// runtime's entries (its images mirror). Root's, as the other files of DISK/etc.
func composeRegistries(disk, entries string) {
	theirs, err := os.ReadFile("/etc/containers/registries.conf")
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		fail("nested: %v", err)
	}
	ours, err := os.ReadFile(entries)
	if err != nil {
		fail("nested: %v", err)
	}
	text := strings.TrimRight(string(theirs), "\n") + "\n\n" + string(ours)
	if err := os.WriteFile(filepath.Join(disk, "etc", "registries.conf"), []byte(text), 0o644); err != nil {
		fail("nested: %v", err)
	}
}

// passwd: the image's /etc/passwd, with a line for uid when it has none (Podman needs a name).
func passwd(uid, gid int) string {
	text, err := os.ReadFile("/etc/passwd")
	if err != nil {
		fail("nested: %v", err)
	}
	scanner := bufio.NewScanner(strings.NewReader(string(text)))
	for scanner.Scan() {
		if fields := strings.Split(scanner.Text(), ":"); len(fields) > 2 && fields[2] == strconv.Itoa(uid) {
			return string(text)
		}
	}
	home := os.Getenv("HOME")
	if home == "" {
		home = "/"
	}
	out := strings.TrimRight(string(text), "\n")
	return fmt.Sprintf("%s\nhandler:x:%d:%d:Handler:%s:/bin/sh\n", out, uid, gid, home)
}

// bind mounts source at target (a file over a file, a folder over a folder), with flags.
func bind(source, target string, flags uintptr) {
	if err := syscall.Mount(source, target, "", syscall.MS_BIND, ""); err != nil {
		fail("%s over %s: %v", source, target, err)
	}
	if flags != 0 {
		remount := uintptr(syscall.MS_REMOUNT|syscall.MS_BIND) | flags
		if err := syscall.Mount("", target, "", remount, ""); err != nil {
			fail("%s: %v", target, err)
		}
	}
}
