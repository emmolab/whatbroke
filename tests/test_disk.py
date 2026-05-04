from whatbroke.checks import disk


def test_is_smart_candidate_device_accepts_whole_disks():
    assert disk._is_smart_candidate_device("sda") is True
    assert disk._is_smart_candidate_device("sdaa") is True
    assert disk._is_smart_candidate_device("nvme0n1") is True


def test_is_smart_candidate_device_rejects_partitions_and_other_nodes():
    assert disk._is_smart_candidate_device("sda1") is False
    assert disk._is_smart_candidate_device("nvme0n1p1") is False
    assert disk._is_smart_candidate_device("loop0") is False
    assert disk._is_smart_candidate_device("md0") is False


def test_check_smart_health_scans_multi_letter_scsi_disks(monkeypatch):
    monkeypatch.setattr(disk.shutil, "which", lambda name: "/usr/sbin/smartctl" if name == "smartctl" else None)
    monkeypatch.setattr(disk.os, "listdir", lambda path: ["sda", "sdaa", "sda1", "nvme0n1", "nvme0n1p1"])

    seen = []

    class Proc:
        def __init__(self, stdout: str):
            self.stdout = stdout

    def fake_run(cmd, timeout=10):
        seen.append(cmd[-1])
        return Proc("SMART overall-health self-assessment test result: PASSED\n")

    monkeypatch.setattr(disk, "_run", fake_run)

    issues = disk._check_smart_health()

    assert issues == []
    assert seen == ["/dev/nvme0n1", "/dev/sda", "/dev/sdaa"]
