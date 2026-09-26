"""S3: suggest the LAN address other devices can most likely reach.

Every case feeds Get-LanDisplayAddress a synthetic snapshot - adapters,
addresses, routes, interface metrics and network categories are its only
inputs, which is what makes the selection testable without touching the real
network adapters.
"""

import json
import subprocess
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = APP_ROOT / "run_portable.ps1"
# The launcher ships for Windows PowerShell 5.1 (run_portable.bat starts it by
# name), so the extracted function is exercised under that interpreter.
POWERSHELL = "powershell.exe"
NO_ADDRESS = "|||none"


def _invoke(functions, expression: str) -> str:
    """Define the named launcher functions in Windows PowerShell 5.1 and run *expression*."""
    escaped_path = str(LAUNCHER).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{escaped_path}', "
        "[ref]$tokens, [ref]$errors); "
    )
    for name in functions:
        command += (
            "$fn=$ast.Find({param($node) $node -is "
            "[System.Management.Automation.Language.FunctionDefinitionAst] -and "
            f"$node.Name -eq '{name}'}}, $true); "
            "Invoke-Expression $fn.Extent.Text; "
        )
    command += expression
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _snapshot(adapters, addresses, routes, metrics=None, profiles=None) -> dict:
    return {
        "adapters": adapters,
        "addresses": addresses,
        "routes": routes,
        "metrics": metrics or [],
        "profiles": profiles or [],
    }


def _suggest(payload: dict) -> str:
    """Return 'address|adapter|category|reason' for one synthetic snapshot."""
    data = json.dumps(payload)
    expression = (
        "$payload = @'\n" + data + "\n'@ | ConvertFrom-Json; "
        "$result = Get-LanDisplayAddress -Adapters $payload.adapters "
        "-Addresses $payload.addresses -Routes $payload.routes "
        "-InterfaceMetrics $payload.metrics -NetworkProfiles $payload.profiles; "
        "($result.Address + '|' + $result.AdapterName + '|' + "
        "$result.NetworkCategory + '|' + $result.Reason)"
    )
    return _invoke(("Get-LanDisplayAddress",), expression)


def _adapter(name, index, up=True, hardware=True) -> dict:
    return {
        "Name": name,
        "Status": "Up" if up else "Disconnected",
        "HardwareInterface": hardware,
        "InterfaceIndex": index,
    }


def _address(index, ip, prefix) -> dict:
    return {"InterfaceIndex": index, "IPAddress": ip, "PrefixLength": prefix}


def _default_route(index, next_hop, metric=0) -> dict:
    return {
        "InterfaceIndex": index,
        "DestinationPrefix": "0.0.0.0/0",
        "NextHop": next_hop,
        "RouteMetric": metric,
    }


# The snapshot from the machine this feature was designed against.
DESIGN_MACHINE_ADAPTERS = (
    _adapter("Ethernet 9", 12),
    _adapter("Virtual Adapter A", 15, hardware=False),
    _adapter("Virtual Adapter B", 16, hardware=False),
    _adapter("Ethernet 7", 9, hardware=False),
    _adapter("Virtual TAP Adapter", 20, up=False, hardware=False),
)
ALEX_ADDRESSES = (
    _address(12, "192.168.1.52", 24),
    _address(15, "10.141.60.53", 24),
    _address(16, "100.100.69.25", 32),
    _address(9, "192.168.56.1", 24),
)
ALEX_ROUTES = (
    _default_route(12, "192.168.1.1", 0),
    {
        "InterfaceIndex": 15,
        "DestinationPrefix": "0.0.0.0/1",
        "NextHop": "10.141.60.1",
        "RouteMetric": 175,
    },
    {
        "InterfaceIndex": 15,
        "DestinationPrefix": "128.0.0.0/1",
        "NextHop": "10.141.60.1",
        "RouteMetric": 175,
    },
)
ALEX_METRICS = (
    {"InterfaceIndex": 12, "InterfaceMetric": 25},
    {"InterfaceIndex": 15, "InterfaceMetric": 1},
    {"InterfaceIndex": 16, "InterfaceMetric": 5},
    {"InterfaceIndex": 9, "InterfaceMetric": 25},
)
ALEX_PROFILES = (
    {"InterfaceIndex": 12, "NetworkCategory": "Public"},
    {"InterfaceIndex": 15, "NetworkCategory": "Public"},
    {"InterfaceIndex": 16, "NetworkCategory": "Private"},
)


class LanAddressSelectionTests(unittest.TestCase):
    def test_alex_snapshot_selects_the_physical_ethernet(self) -> None:
        payload = _snapshot(
            DESIGN_MACHINE_ADAPTERS, ALEX_ADDRESSES, ALEX_ROUTES, ALEX_METRICS, ALEX_PROFILES
        )

        self.assertEqual("192.168.1.52|Ethernet 9|Public|ok", _suggest(payload))

    def test_virtual_adapter_with_a_lower_metric_default_route_does_not_win(self) -> None:
        routes = ALEX_ROUTES + (_default_route(15, "10.141.60.1", 0),)

        payload = _snapshot(
            DESIGN_MACHINE_ADAPTERS, ALEX_ADDRESSES, routes, ALEX_METRICS, ALEX_PROFILES
        )

        self.assertEqual("192.168.1.52|Ethernet 9|Public|ok", _suggest(payload))

    def test_virtual_adapter_with_a_default_route_is_not_guessed(self) -> None:
        payload = _snapshot(
            (_adapter("Virtual TAP Adapter", 21, hardware=False),),
            (_address(21, "10.8.0.2", 24),),
            (_default_route(21, "10.8.0.1", 1),),
            ({"InterfaceIndex": 21, "InterfaceMetric": 1},),
        )

        self.assertEqual(NO_ADDRESS, _suggest(payload))

    def test_only_virtual_adapters_are_not_guessed(self) -> None:
        payload = _snapshot(
            (
                _adapter("Virtual Adapter B", 16, hardware=False),
                _adapter("VirtualBox Host-Only", 9, hardware=False),
            ),
            (_address(16, "100.100.69.25", 32), _address(9, "192.168.56.1", 24)),
            (_default_route(16, "100.100.69.1"), _default_route(9, "192.168.56.1")),
        )

        self.assertEqual(NO_ADDRESS, _suggest(payload))

    def test_physical_adapter_without_a_default_gateway_is_not_guessed(self) -> None:
        payload = _snapshot(
            (_adapter("Ethernet", 12),),
            (_address(12, "192.168.1.52", 24),),
            (),
        )

        self.assertEqual(NO_ADDRESS, _suggest(payload))

    def test_hyperv_external_switch_is_not_guessed(self) -> None:
        # The physical adapter has no IPv4 address any more; the address and
        # the default route sit on the vEthernet adapter.
        payload = _snapshot(
            (
                _adapter("Ethernet", 12, up=True, hardware=True),
                _adapter("vEthernet (External)", 24, hardware=False),
            ),
            (_address(24, "192.168.1.52", 24),),
            (_default_route(24, "192.168.1.1"),),
        )

        self.assertEqual(NO_ADDRESS, _suggest(payload))

    def test_gateway_outside_the_address_subnet_is_not_guessed(self) -> None:
        payload = _snapshot(
            (_adapter("Ethernet", 12),),
            (_address(12, "192.168.1.52", 24),),
            (_default_route(12, "192.168.2.1"),),
        )

        self.assertEqual(NO_ADDRESS, _suggest(payload))

    def test_link_local_and_cgnat_addresses_are_never_selected(self) -> None:
        for ip in ("169.254.10.20", "100.64.1.5"):
            with self.subTest(ip=ip):
                payload = _snapshot(
                    (_adapter("Ethernet", 12),),
                    (_address(12, ip, 16),),
                    (_default_route(12, ip.rsplit(".", 1)[0] + ".1"),),
                )

                self.assertEqual(NO_ADDRESS, _suggest(payload))

    def test_non_private_addresses_are_not_candidates(self) -> None:
        for ip in ("172.32.1.5", "8.8.8.8", "11.0.0.7"):
            with self.subTest(ip=ip):
                payload = _snapshot(
                    (_adapter("Ethernet", 12),),
                    (_address(12, ip, 24),),
                    (_default_route(12, ip.rsplit(".", 1)[0] + ".1"),),
                )

                self.assertEqual(NO_ADDRESS, _suggest(payload))

    def test_private_ranges_are_accepted(self) -> None:
        cases = (
            ("10.4.0.9", "10.4.0.1"),
            ("172.16.5.10", "172.16.5.1"),
            ("172.31.255.10", "172.31.255.1"),
            ("192.168.1.52", "192.168.1.1"),
        )
        for ip, gateway in cases:
            with self.subTest(ip=ip):
                payload = _snapshot(
                    (_adapter("Ethernet", 12),),
                    (_address(12, ip, 24),),
                    (_default_route(12, gateway),),
                )

                self.assertEqual(
                    "%s|Ethernet||ok" % ip, _suggest(payload)
                )

    def test_lower_metric_wins_between_two_physical_adapters(self) -> None:
        adapters = (_adapter("Ethernet", 12), _adapter("WLAN", 13))
        addresses = (_address(12, "192.168.1.52", 24), _address(13, "192.168.1.77", 24))
        routes = (_default_route(12, "192.168.1.1"), _default_route(13, "192.168.1.1"))
        cases = (
            ((25, 50), "192.168.1.52|Ethernet|"),
            ((50, 25), "192.168.1.77|WLAN|"),
            ((25, 25), "192.168.1.52|Ethernet|"),
        )
        for (ethernet_metric, wlan_metric), expected_prefix in cases:
            with self.subTest(metrics=(ethernet_metric, wlan_metric)):
                payload = _snapshot(
                    adapters,
                    addresses,
                    routes,
                    (
                        {"InterfaceIndex": 12, "InterfaceMetric": ethernet_metric},
                        {"InterfaceIndex": 13, "InterfaceMetric": wlan_metric},
                    ),
                )

                self.assertTrue(_suggest(payload).startswith(expected_prefix))

    def test_route_metric_and_interface_metric_are_added(self) -> None:
        adapters = (_adapter("Ethernet", 12), _adapter("WLAN", 13))
        addresses = (
            _address(12, "192.168.1.52", 24),
            _address(13, "192.168.1.77", 24),
        )
        cases = (
            # WLAN: 0 + 40 beats Ethernet: 50 + 0, and vice versa below.
            ((50, 0), (0, 40), "192.168.1.77|WLAN|"),
            ((10, 30), (0, 60), "192.168.1.52|Ethernet|"),
        )
        for (ethernet_route, ethernet_interface), (wlan_route, wlan_interface), expected in cases:
            with self.subTest(expected=expected):
                payload = _snapshot(
                    adapters,
                    addresses,
                    (
                        _default_route(12, "192.168.1.1", ethernet_route),
                        _default_route(13, "192.168.1.1", wlan_route),
                    ),
                    (
                        {"InterfaceIndex": 12, "InterfaceMetric": ethernet_interface},
                        {"InterfaceIndex": 13, "InterfaceMetric": wlan_interface},
                    ),
                )

                self.assertTrue(_suggest(payload).startswith(expected))

    def test_empty_snapshot_returns_no_address(self) -> None:
        self.assertEqual(NO_ADDRESS, _suggest(_snapshot((), (), ())))


class LanAddressLauncherWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = LAUNCHER.read_text(encoding="utf-8")

    def test_launcher_projects_the_read_only_cmdlets_into_the_selector(self) -> None:
        self.assertNotIn("Get-NetIPConfiguration", self.source)
        for projection in (
            "HardwareInterface = $_.HardwareInterface",
            "InterfaceIndex = $_.ifIndex",
            "$_.IPAddress",
            "$_.PrefixLength",
            "$_.NextHop",
            "$_.RouteMetric",
            "$_.InterfaceMetric",
            "$_.NetworkCategory",
        ):
            with self.subTest(projection=projection):
                self.assertIn(projection, self.source)
        self.assertIn(
            "$lanSuggestion = Get-LanDisplayAddress -Adapters $lanAdapters "
            "-Addresses $lanAddresses -Routes $lanRoutes "
            "-InterfaceMetrics $lanInterfaceMetrics -NetworkProfiles $lanProfiles",
            self.source,
        )

    def test_launcher_only_reads_network_state(self) -> None:
        for forbidden in (
            "Set-NetConnectionProfile",
            "Set-NetFirewallProfile",
            "New-NetFirewallRule",
            "Set-NetIPInterface",
            "Set-NetAdapter",
            "New-NetRoute",
            "Remove-NetRoute",
            "Set-NetIPAddress",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.source)

    def test_url_and_adapter_name_are_on_separate_lines(self) -> None:
        url_line = next(
            line
            for line in self.source.splitlines()
            if 'Write-Host "http://${displayHost}:$Port"' in line
        )
        adapter_line = next(
            line
            for line in self.source.splitlines()
            if "（网卡：$detectedLanAdapter）" in line
        )

        self.assertNotIn("网卡", url_line)
        self.assertNotIn("http", adapter_line)
        self.assertLess(self.source.index(url_line), self.source.index(adapter_line))

    def test_not_guessing_prints_the_hand_check_hint(self) -> None:
        self.assertIn("未能确定其他设备可用的局域网地址", self.source)
        self.assertIn("ipconfig", self.source)

    def test_public_network_hint_mentions_the_firewall_and_keeps_the_setting(self) -> None:
        self.assertIn("此网络被 Windows 标为「公用」", self.source)
        self.assertIn("Windows 防火墙是否有允许本程序入站的规则", self.source)
        self.assertIn("改为专用本身也不保证能连通", self.source)

    def test_launcher_passes_the_resolved_address_to_the_app(self) -> None:
        self.assertIn("$env:BASHI_LAN_DISPLAY_HOST = $detectedLanIp", self.source)
        self.assertIn("$env:BASHI_LAN_DISPLAY_HOST = $BindHost.Trim()", self.source)
        self.assertIn("BASHI_LAN_DISPLAY_HOST", (APP_ROOT / "app.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
