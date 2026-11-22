// handler-relay: the command of a sandbox on Apple container, whose networks do not isolate
// (apple/container#2062): a filtered sandbox has no network, only this relay to the host.
//
//	handler-relay [--user UID:GID] [--host /run/handler-host.sock \
//	    --listen tcp:127.42.0.1:3128=egress --listen unix:/run/handler-app/handler.sock=s0/handler.sock \
//	    --serve unix:/run/handler-app/app.sock=s0/app.sock] -- ARGV...
//
// With --user, started as root with CAP_SETUID, CAP_SETGID, CAP_SETPCAP and CAP_CHOWN only, it
// gives the host's socket to that user, empties the capability bounding set, sets
// no_new_privs (which Apple's `container` cannot) and becomes the user, before anything else.
//
// With --overlay LOWER:UPPER:WORK:TARGET (repeatable, with --user; CAP_SYS_ADMIN too; a cache
// inside another after it), a cache:
// LOWER the cache's folder (read-only), UPPER and WORK the sandbox's own writes, TARGET where the
// sandbox sees it. Once the bounding set is empty and no_new_privs set, the relay opens
// /dev/fuse, mounts TARGET with it, and hands the mount to fuse-overlayfs (beside this program)
// running as the user, every file shown as the user's: the program serving the overlay has no
// capability, and the sandbox never has LOWER writable.
//
// With --host, a sandbox with no network reaches the host through that one socket (Apple's
// `container run --volume <socket>:<path>`: each connect a new connection to it). Each listener
// gives the sandbox's programs an address leading to a target of the host: its network filter's
// proxy, handlerd's socket for an app. A program's connection becomes a new connection to the
// host's socket, which first says the target's name ("egress\n"), then carries the stream.
//
// The other way (--serve), a socket of the sandbox the host connects to: the host cannot connect
// into the VM (Apple refuses the Mac a socket made in a VM, apple/container#2101), so the relay
// waits on the host's side: `parked` connections to the host's socket, each saying "<NAME\n" and
// waiting. The host writes one byte on one when a client of its own connects; the relay joins it
// to that socket, here, and parks another in its place. Every connection is opened from here.
//
// It runs ARGV as its child once the listeners are up (stdio inherited) and, on a terminal, that
// terminal has its size; it passes signals on, and exits with its exit code. Linux only.
package main

import (
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

type listeners []string

func (l *listeners) String() string     { return strings.Join(*l, ",") }
func (l *listeners) Set(v string) error { *l = append(*l, v); return nil }

func main() {
	if len(os.Args) > 1 && os.Args[1] == "merge" { // merge.go
		mergeMain(os.Args[2:])
	}
	user := flag.String("user", "", "UID:GID to become (started as root)")
	host := flag.String("host", "", "the host's socket")
	var listen listeners
	flag.Var(&listen, "listen", "tcp:HOST:PORT=NAME or unix:PATH=NAME (repeatable, with --host)")
	var serves listeners
	flag.Var(&serves, "serve", "unix:PATH=NAME, the host reaching PATH as NAME (repeatable, with --host)")
	var mounts setup
	flag.Var(&mounts.overlays, "overlay", "LOWER:UPPER:WORK:TARGET, a cache's overlay (repeatable, with --user)")
	flag.StringVar(&mounts.nested, "nested", "", "DISK: what an engine inside needs (with --user)")
	flag.StringVar(&mounts.registries, "registries", "", "FILE: added to the image's registries.conf, on the disk (with --nested)")
	flag.Parse()
	if (len(listen) > 0 || len(serves) > 0) && *host == "" {
		fail("--listen and --serve need --host")
	}
	if (len(mounts.overlays) > 0 || mounts.nested != "") && *user == "" {
		fail("--overlay and --nested need --user")
	}
	if flag.NArg() == 0 {
		fail("no command")
	}
	if *user != "" {
		become(*user, *host, mounts)
	}
	for _, spec := range listen {
		addr, name, ok := strings.Cut(spec, "=")
		network, address, ok2 := strings.Cut(addr, ":")
		if !ok || !ok2 || (network != "tcp" && network != "unix") {
			fail("bad --listen %q", spec)
		}
		if network == "unix" {
			os.Remove(address)
		}
		l, err := net.Listen(network, address)
		if err != nil {
			fail("listen %s: %v", spec, err)
		}
		go serve(l, *host, name)
	}
	for _, spec := range serves {
		addr, name, ok := strings.Cut(spec, "=")
		network, address, ok2 := strings.Cut(addr, ":")
		if !ok || !ok2 || network != "unix" {
			fail("bad --serve %q", spec)
		}
		for i := 0; i < parked; i++ {
			go park(*host, name, address)
		}
	}
	os.Exit(run(flag.Args()))
}

// parked: the connections waiting on the host's side for each served socket (the host keeps at
// most 4: more are closed); one taken is replaced at once.
const parked = 2

// park waits on the host's side for its clients, one at a time, for good: a connection to the
// host's socket ("<NAME\n"), then its byte, then the socket here joined to it.
func park(host, name, address string) {
	for {
		there, err := net.Dial("unix", host)
		if err == nil {
			_, err = fmt.Fprintf(there, "<%s\n", name)
		}
		var woken [1]byte
		if err == nil {
			_, err = io.ReadFull(there, woken[:])
		}
		if err != nil { // the host away (stopping), or this one closed: again, not in a loop
			if there != nil {
				there.Close()
			}
			time.Sleep(200 * time.Millisecond)
			continue
		}
		go func() {
			here, err := net.Dial("unix", address)
			if err != nil { // nothing listens yet: the host's client sees its connection end
				there.Close()
				return
			}
			join(here, there)
		}()
	}
}

// setup: what the relay sets up as root before it becomes the user.
type setup struct {
	overlays   listeners
	nested     string // the disk, when an engine runs inside (nested.go)
	registries string // the runtime's registries.conf entries (its images mirror), with nested
}

// become gives the host's socket to uid:gid, then drops every privilege for good: the bounding
// set and no_new_privs on every thread (children inherit them), then the groups and ids. The
// caches' overlays and the disk's folders are mounted in between: what the relay still holds
// (its effective capabilities) mounts them, what it starts to serve them inherits neither. With
// --nested the bounding set keeps an engine's capabilities and no_new_privs is not set: the
// engine's newuidmap and newgidmap need their file capabilities (nested.go).
func become(user, host string, mounts setup) {
	uidText, gidText, ok := strings.Cut(user, ":")
	uid, err1 := strconv.Atoi(uidText)
	gid, err2 := strconv.Atoi(gidText)
	if !ok || err1 != nil || err2 != nil {
		fail("bad --user %q", user)
	}
	if host != "" {
		if err := os.Chown(host, uid, gid); err != nil {
			fail("the host's socket: %v", err)
		}
	}
	for _, spec := range mounts.overlays {
		prepareOverlay(spec, uid, gid)
	}
	if mounts.nested != "" {
		prepareNested(mounts.nested, uid, gid)
		if mounts.registries != "" {
			composeRegistries(mounts.nested, mounts.registries)
		}
	}
	for c := uintptr(0); c <= 63; c++ { // EINVAL past the kernel's last capability
		if mounts.nested == "" || !engineCaps[c] {
			syscall.AllThreadsSyscall(syscall.SYS_PRCTL, prCapbsetDrop, c, 0)
		}
	}
	if mounts.nested == "" {
		if _, _, e := syscall.AllThreadsSyscall(syscall.SYS_PRCTL, prSetNoNewPrivs, 1, 0); e != 0 {
			fail("no_new_privs: %v", e)
		}
	}
	for _, spec := range mounts.overlays {
		mountOverlay(spec, uid, gid)
	}
	if err := syscall.Setgroups(nil); err != nil {
		fail("groups: %v", err)
	}
	if err := syscall.Setresgid(gid, gid, gid); err != nil {
		fail("gid %d: %v", gid, err)
	}
	if err := syscall.Setresuid(uid, uid, uid); err != nil {
		fail("uid %d: %v", uid, err)
	}
}

const (
	prCapbsetDrop   = 24 // PR_CAPBSET_DROP
	prSetNoNewPrivs = 38 // PR_SET_NO_NEW_PRIVS
)

// overlayParts splits --overlay's LOWER:UPPER:WORK:TARGET, four absolute paths.
func overlayParts(spec string) (lower, upper, work, target string) {
	parts := strings.Split(spec, ":")
	if len(parts) != 4 {
		fail("bad --overlay %q", spec)
	}
	for _, p := range parts {
		if !strings.HasPrefix(p, "/") || strings.Contains(p, ",") {
			fail("bad --overlay %q", spec)
		}
	}
	return parts[0], parts[1], parts[2], parts[3]
}

// prepareOverlay makes the sandbox's writes' folders, the user's (the mount point is made when
// mounted: inside another cache, it is made in that cache's overlay).
func prepareOverlay(spec string, uid, gid int) {
	_, upper, work, target := overlayParts(spec)
	for _, dir := range []string{upper, work} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			fail("overlay %s: %v", target, err)
		}
		if err := os.Chown(dir, uid, gid); err != nil {
			fail("overlay %s: %v", target, err)
		}
	}
}

// overlayWait: how long the relay waits for an overlay's program to answer, at most.
const overlayWait = 10 * time.Second

// mountOverlay mounts TARGET with a /dev/fuse of its own, then starts fuse-overlayfs on that
// mount as uid:gid: no capability (the bounding set is empty, the ids not root's), no_new_privs.
func mountOverlay(spec string, uid, gid int) {
	lower, upper, work, target := overlayParts(spec)
	self, err := os.Executable()
	if err != nil {
		fail("overlay %s: %v", target, err)
	}
	program := filepath.Join(filepath.Dir(self), "fuse-overlayfs")
	if err := os.MkdirAll(target, 0o755); err != nil {
		fail("overlay %s: %v", target, err)
	}
	dev, err := os.OpenFile("/dev/fuse", os.O_RDWR, 0)
	if err != nil {
		fail("overlay %s: %v", target, err)
	}
	options := fmt.Sprintf(
		"fd=%d,rootmode=40000,user_id=%d,group_id=%d,allow_other,default_permissions",
		dev.Fd(), uid, gid)
	flags := uintptr(syscall.MS_NOSUID | syscall.MS_NODEV)
	if err := syscall.Mount("fuse-overlayfs", target, "fuse.fuse-overlayfs", flags, options); err != nil {
		fail("overlay %s: mount: %v", target, err)
	}
	cmd := exec.Command(program, "-f", "-o", fmt.Sprintf(
		"lowerdir=%s,upperdir=%s,workdir=%s,squash_to_uid=%d,squash_to_gid=%d",
		lower, upper, work, uid, gid), "/dev/fd/3")
	cmd.ExtraFiles = []*os.File{dev} // its fd 3
	cmd.Stderr = os.Stderr
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Credential: &syscall.Credential{Uid: uint32(uid), Gid: uint32(gid), Groups: []uint32{}},
		Setsid:     true, // a terminal's signals are the agent's
	}
	if err := cmd.Start(); err != nil {
		fail("overlay %s: %v", target, err)
	}
	dev.Close() // the mount is the program's alone: if it ends, the mount answers ENOTCONN
	go cmd.Wait()
	answered := make(chan error, 1)
	go func() { _, err := os.Stat(target); answered <- err }()
	select {
	case err := <-answered:
		if err != nil {
			fail("overlay %s: %v", target, err)
		}
	case <-time.After(overlayWait):
		fail("overlay %s: fuse-overlayfs did not answer", target)
	}
}

func serve(l net.Listener, host, name string) {
	for {
		c, err := l.Accept()
		if err != nil {
			fail("listener %s: %v", name, err)
		}
		go stream(c, host, name)
	}
}

func stream(c net.Conn, host, name string) {
	there, err := net.Dial("unix", host)
	if err != nil {
		c.Close()
		return
	}
	if _, err := fmt.Fprintf(there, "%s\n", name); err != nil {
		c.Close()
		there.Close()
		return
	}
	join(c, there)
}

type halfCloser interface{ CloseWrite() error }

// join copies both ways; each side's end is passed on as a half close.
func join(a, b net.Conn) {
	var wg sync.WaitGroup
	copyHalf := func(dst, src net.Conn) {
		defer wg.Done()
		io.Copy(dst, src)
		if h, ok := dst.(halfCloser); ok {
			h.CloseWrite()
		} else {
			dst.Close()
		}
	}
	wg.Add(2)
	go copyHalf(a, b)
	go copyHalf(b, a)
	wg.Wait()
	a.Close()
	b.Close()
}

// sizeWait: how long a terminal's process waits for its terminal's size, at most.
const sizeWait = 2 * time.Second

// waitForSize returns once stdin, a terminal, has a size (at once when it is not a terminal):
// Apple's `container start --attach` sizes the terminal just after the process starts, and a
// program asking its size at once (a full-screen one) would get 0x0.
func waitForSize() {
	var size struct{ rows, cols, x, y uint16 }
	deadline := time.Now().Add(sizeWait)
	for {
		_, _, errno := syscall.Syscall(
			syscall.SYS_IOCTL, 0, syscall.TIOCGWINSZ, uintptr(unsafe.Pointer(&size)))
		if errno != 0 || (size.rows > 0 && size.cols > 0) || time.Now().After(deadline) {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// run starts argv, passes signals on, and returns its exit code (128+n when killed by signal n).
func run(argv []string) int {
	waitForSize()
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	// what the runtime sends (stopping the sandbox) is passed on; what a terminal sends (Ctrl-C,
	// a resize) already reaches the child, in the same process group: handled here (so the
	// child gets the default handling, not an inherited "ignore"), dropped
	passed := []os.Signal{syscall.SIGTERM, syscall.SIGHUP, syscall.SIGUSR1, syscall.SIGUSR2}
	dropped := []os.Signal{syscall.SIGINT, syscall.SIGQUIT, syscall.SIGWINCH, syscall.SIGTSTP}
	signals := make(chan os.Signal, 8)
	signal.Notify(signals, passed...)
	signal.Notify(make(chan os.Signal, 8), dropped...)
	if err := cmd.Start(); err != nil {
		fail("cannot start %s: %v", argv[0], err)
	}
	go func() {
		for s := range signals {
			cmd.Process.Signal(s)
		}
	}()
	err := cmd.Wait()
	if exit, ok := err.(*exec.ExitError); ok {
		if status, ok := exit.Sys().(syscall.WaitStatus); ok && status.Signaled() {
			return 128 + int(status.Signal())
		}
		return exit.ExitCode()
	}
	if err != nil {
		return 127
	}
	return 0
}

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "handler-relay: "+format+"\n", args...)
	os.Exit(125)
}
