#!/usr/bin/bash
# Proves the team VLAN filter (freezy-field.nft) against real packets, without root and without touching
# the machine's own network: everything happens inside a private user and network namespace.
#
#   deploy/host/test_freezy_firewall.sh
#
# Layout built for the test: a "field server" with the FMS address and two team VLAN interfaces, and
# one driver station behind each. Each check runs twice: first with no rules, to show the path is
# really open (so a "blocked" result means the rules blocked it), then with the rules loaded.
set -u

if [ "${FREEZY_FW_TEST_INNER:-}" != 1 ]; then
    exec env FREEZY_FW_TEST_INNER=1 unshare -rnm --kill-child "$0" "$@"
fi

here=$(cd "$(dirname "$0")" && pwd)
mount -t tmpfs tmpfs /run
tmp=$(mktemp -d -p /run)
cat > "$tmp/freezy-field-vars.nft" <<'VARS'
define team_vlans = { "vlan10", "vlan20" }
define transit_ifs = { "cheesy_transit" }
define transit_address = 192.168.254.253
define fms_address = 10.0.100.5
define fms_network = 10.0.100.0/24
define team_gateway_host = 0.0.0.4
VARS

ip link set lo up
ip link add fms0 type dummy && ip addr add 10.0.100.5/24 dev fms0 && ip link set fms0 up
sysctl -qw net.ipv4.ip_forward=1
for spec in "ds1 vlan10 10.2.54" "ds2 vlan20 10.11.14"; do
    set -- $spec
    ip netns add "$1"
    ip link add "$2" type veth peer name eth0 netns "$1"
    ip addr add "$3.4/24" dev "$2" && ip link set "$2" up
    ip -n "$1" link set lo up
    ip -n "$1" addr add "$3.20/24" dev eth0 && ip -n "$1" link set eth0 up
    ip -n "$1" route add default via "$3.4"
done

# The jump machine, on the field server's transit address.
ip netns add jump
ip link add cheesy_transit type veth peer name eth0 netns jump
ip addr add 192.168.254.253/29 dev cheesy_transit && ip link set cheesy_transit up
ip -n jump link set lo up
ip -n jump addr add 192.168.254.254/29 dev eth0 && ip -n jump link set eth0 up
ip -n jump route add 10.0.0.0/8 via 192.168.254.253

# Listeners: the arena on the field server (web 8080, DS control 1750, DS status 1160/udp, ssh 22) on
# every address, as host networking gives it, and a web server on the second team's driver station.
cat > "$tmp/listen.py" <<'PY'
import socket, sys, selectors
sel = selectors.DefaultSelector()
for spec in sys.argv[1:]:
    kind, addr, port = spec.split(":")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM if kind == "tcp" else socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((addr, int(port)))
    if kind == "tcp":
        s.listen()
    sel.register(s, selectors.EVENT_READ, kind)
print("ready", flush=True)
while True:
    for key, _ in sel.select():
        if key.data == "tcp":
            c, _ = key.fileobj.accept(); c.sendall(b"ok"); c.close()
        else:
            data, peer = key.fileobj.recvfrom(100); key.fileobj.sendto(b"ok", peer)
PY
cat > "$tmp/probe.py" <<'PY'
import socket, sys
kind, addr, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM if kind == "tcp" else socket.SOCK_DGRAM)
s.settimeout(1.5)
try:
    s.connect((addr, port))
    if kind == "udp":
        s.send(b"hi")
    sys.exit(0 if s.recv(10) == b"ok" else 1)
except OSError:
    sys.exit(1)
PY
python3 "$tmp/listen.py" tcp:0.0.0.0:8080 tcp:0.0.0.0:1750 tcp:0.0.0.0:22 \
    udp:10.0.100.5:1160 udp:10.2.54.4:1160 udp:10.2.54.4:67 > "$tmp/l1" &
ip netns exec ds2 python3 "$tmp/listen.py" tcp:0.0.0.0:8080 > "$tmp/l2" &
ip netns exec ds1 python3 "$tmp/listen.py" tcp:0.0.0.0:1741 > "$tmp/l3" &
for f in l1 l2 l3; do
    for _ in $(seq 50); do grep -q ready "$tmp/$f" 2>/dev/null && break; sleep 0.1; done
done

fail=0
# check <phase> <open|blocked> <description> <command...>
check() {
    phase=$1 want=$2 what=$3; shift 3
    if "$@" >/dev/null 2>&1; then got=open; else got=blocked; fi
    if [ "$got" = "$want" ]; then
        echo "ok    [$phase] $what: $got"
    else
        echo "FAIL  [$phase] $what: $got, expected $want"; fail=1
    fi
}
# The probes are small scripts on PATH so they can run inside a driver station's namespace too.
mkdir "$tmp/bin"
printf '#!/usr/bin/bash\nexec python3 %s "$@"\n' "$tmp/probe.py" > "$tmp/bin/probe"
printf '#!/usr/bin/bash\nexec ping -c1 -W1 "$1"\n' > "$tmp/bin/pingc"
# A DHCP-shaped packet: UDP from port 68 to port 67 on the team gateway.
cat > "$tmp/bin/dhcp" <<'PY'
#!/usr/bin/python3
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(1.5)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", 68)); s.sendto(b"hi", ("10.2.54.4", 67)); sys.exit(0 if s.recv(10) == b"ok" else 1)
except OSError:
    sys.exit(1)
PY
chmod +x "$tmp"/bin/*
PATH="$tmp/bin:$PATH"
ds1() { ip netns exec ds1 "$@"; }
jump() { ip netns exec jump "$@"; }

run_checks() {
    phase=$1 closed=$2   # closed = what the filtered paths should be in this phase
    check "$phase" open    "DS control connection, tcp 1750 to the FMS address" ds1 probe tcp 10.0.100.5 1750
    check "$phase" open    "DS status packets, udp 1160 to the FMS address"     ds1 probe udp 10.0.100.5 1160
    check "$phase" open    "ping the FMS address"                               ds1 pingc 10.0.100.5
    check "$phase" open    "ping the team's own gateway"                        ds1 pingc 10.2.54.4
    check "$phase" open    "DHCP request to the team gateway"                   ds1 dhcp
    check "$phase" open    "field server opens a connection to the DS"          probe tcp 10.2.54.20 1741
    check "$phase" $closed "arena web pages on the FMS address, tcp 8080"       ds1 probe tcp 10.0.100.5 8080
    check "$phase" $closed "arena web pages on the team gateway, tcp 8080"      ds1 probe tcp 10.2.54.4 8080
    check "$phase" $closed "ssh to the field server"                            ds1 probe tcp 10.0.100.5 22
    check "$phase" $closed "DS control port on the team gateway address"        ds1 probe tcp 10.2.54.4 1750
    check "$phase" $closed "udp 1160 on the team gateway address"               ds1 probe udp 10.2.54.4 1160
    check "$phase" $closed "ping another team's driver station"                 ds1 pingc 10.11.14.20
    check "$phase" $closed "connect to another team's driver station"           ds1 probe tcp 10.11.14.20 8080
    check "$phase" open    "jump machine: ssh to the field server"              jump probe tcp 192.168.254.253 22
    check "$phase" open    "jump machine: ping the field server"                jump pingc 192.168.254.253
    check "$phase" $closed "jump machine: arena web pages"                      jump probe tcp 192.168.254.253 8080
    check "$phase" $closed "jump machine: the FMS address through the server"   jump probe tcp 10.0.100.5 22
    check "$phase" $closed "jump machine: routed on to a team network"          jump probe tcp 10.2.54.20 1741
    check "$phase" $closed "team VLAN routed out to the transit network"        ds1 pingc 192.168.254.254
}

run_checks "no rules" open
if ! nft -I "$tmp" -f "$here/freezy-field.nft"; then
    echo "FAIL  the rules did not load"; exit 1
fi
run_checks "filtered" blocked
# Loading the file a second time must replace the table, not stack a second copy of the rules.
nft -I "$tmp" -f "$here/freezy-field.nft"
check "reloaded" open "rules load a second time" test "$(nft list tables | grep -c freezy_field)" = 1
run_checks "reloaded" blocked

[ $fail = 0 ] && echo "PASS" || echo "FAILED"
exit $fail
