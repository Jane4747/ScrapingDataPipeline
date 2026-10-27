import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from pipeline import catalog, runner


ROOT = Path(__file__).resolve().parents[1]


class RunnerRegressionTest(unittest.TestCase):
    def government_args(self, **changes):
        values = dict(site="sample", start_date=None, all_sites=False,
                      only_start_date=False, delivery="excel")
        values.update(changes)
        return types.SimpleNamespace(**values)

    def make_government(self, base):
        repo = Path(base) / "government"
        (repo / "codes").mkdir(parents=True)
        (repo / "codes" / "sample.py").write_text("", encoding="utf-8")
        (repo / "xls_files").mkdir()
        output = Path(base) / "output"
        output.mkdir()
        return repo, output

    def test_cli_and_json_delivery_work_without_pandas(self):
        code = """
import builtins, json, tempfile
from pathlib import Path
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'pandas' or name.startswith('pandas.'):
        raise ImportError('pandas intentionally unavailable')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from pipeline.cli import main
from pipeline.runner import _write_delivery
with tempfile.TemporaryDirectory() as tmp:
    path = _write_delivery([{'title': 'test'}], 'json', Path(tmp))
    assert json.loads(path.read_text(encoding='utf-8'))[0]['title'] == 'test'
try:
    main(['--help'])
except SystemExit as exc:
    assert exc.code == 0
"""
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", code],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)

    def test_single_site_exports_new_workbooks_including_duplicate_basenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, output = self.make_government(tmp)
            historical = repo / "xls_files" / "history.xlsx"
            historical.write_bytes(b"old")

            def produce(command, cwd):
                for folder in ["a", "b"]:
                    target = repo / "xls_files" / folder / "result.xlsx"
                    target.parent.mkdir()
                    target.write_bytes(folder.encode())

            with patch.dict(runner.TOOLS, {"goverment_spider": {"path": repo}}), \
                    patch.object(runner, "_subprocess", side_effect=produce):
                result = runner._run_goverment({}, self.government_args(), output)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["success_count"], 2)
            self.assertEqual(len(result["files"]), 2)
            self.assertEqual((output / "a" / "result.xlsx").read_bytes(), b"a")
            self.assertEqual((output / "b" / "result.xlsx").read_bytes(), b"b")
            self.assertFalse((output / historical.name).exists())

    def test_single_site_does_not_report_historical_file_as_current_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, output = self.make_government(tmp)
            (repo / "xls_files" / "history.xlsx").write_bytes(b"old")
            with patch.dict(runner.TOOLS, {"goverment_spider": {"path": repo}}), \
                    patch.object(runner, "_subprocess"):
                result = runner._run_goverment({}, self.government_args(), output)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["success_count"], 0)
            self.assertEqual(result["failure_count"], 1)
            self.assertEqual(result["files"], [])
            self.assertEqual(list(output.iterdir()), [])

    def test_existing_workbook_content_change_detected_with_same_size_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, output = self.make_government(tmp)
            source = repo / "xls_files" / "result.xlsx"
            source.write_bytes(b"old")
            before_stat = source.stat()

            def update(command, cwd):
                source.write_bytes(b"new")
                os.utime(source, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))

            with patch.dict(runner.TOOLS, {"goverment_spider": {"path": repo}}), \
                    patch.object(runner, "_subprocess", side_effect=update):
                result = runner._run_goverment({}, self.government_args(), output)
            self.assertEqual(result["status"], "completed")
            self.assertEqual((output / "result.xlsx").read_bytes(), b"new")

    def test_all_sites_uses_same_no_stale_output_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, output = self.make_government(tmp)
            (repo / "xls_files" / "history.xlsx").write_bytes(b"old")
            with patch.dict(runner.TOOLS, {"goverment_spider": {"path": repo}}), \
                    patch.object(runner, "_subprocess"):
                result = runner._run_goverment({}, self.government_args(site=None, all_sites=True), output)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["files"], [])

    def test_single_site_text_output_is_exported_without_unrelated_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, output = self.make_government(tmp)
            folder = repo / "files" / "2026年10月" / "2026-10-21" / "国家级"
            folder.mkdir(parents=True)
            (folder / "old.txt").write_text("其他部门\t通知\t旧政策\t2026-10-01\thttps://example.com/old\n", encoding="utf-8")

            def produce(command, cwd):
                (folder / "current.txt").write_text("卫健部门\t通知\t医疗装备政策\t2026-10-21\thttps://example.com/new\n", encoding="utf-8")

            with patch.dict(runner.TOOLS, {"goverment_spider": {"path": repo}}), \
                    patch.object(runner, "_subprocess", side_effect=produce):
                result = runner._run_goverment({}, self.government_args(delivery="json"), output)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["success_count"], 1)
            rows = json.loads(Path(result["files"][0]).read_text(encoding="utf-8"))
            self.assertEqual(rows[0]["标题"], "医疗装备政策")
            self.assertEqual(len(rows), 1)

    def test_single_site_malformed_text_is_partial_and_date_filter_applies(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, output = self.make_government(tmp)
            folder = repo / "files"
            folder.mkdir()

            def produce(command, cwd):
                (folder / "current.txt").write_text(
                    "卫健部门\t通知\t当前政策\t2026-10-21\thttps://example.com/new\n"
                    "卫健部门\t通知\t范围外\t2026-09-01\thttps://example.com/old\n"
                    "malformed\tline\n", encoding="utf-8")

            with patch.dict(runner.TOOLS, {"goverment_spider": {"path": repo}}), \
                    patch.object(runner, "_subprocess", side_effect=produce):
                result = runner._run_goverment({}, self.government_args(
                    delivery="json", only_start_date=True, start_date="2026-10-21"), output)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["success_count"], 1)
            self.assertEqual(result["failure_count"], 1)

    @unittest.skipUnless(importlib.util.find_spec("pandas") and importlib.util.find_spec("openpyxl"), "Full Excel dependencies unavailable")
    def test_single_site_text_generates_readable_excel(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as tmp:
            repo, output = self.make_government(tmp)
            folder = repo / "files"
            folder.mkdir()

            def produce(command, cwd):
                (folder / "current.txt").write_text("卫健部门\t通知\t医疗装备政策\t2026-10-21\thttps://example.com/new\n", encoding="utf-8")

            with patch.dict(runner.TOOLS, {"goverment_spider": {"path": repo}}), \
                    patch.object(runner, "_subprocess", side_effect=produce):
                result = runner._run_goverment({}, self.government_args(), output)
            self.assertEqual(result["status"], "completed")
            table = pd.read_excel(result["files"][0])
            self.assertEqual(table.iloc[0]["标题"], "医疗装备政策")

    @unittest.skipUnless(importlib.util.find_spec("pandas") and importlib.util.find_spec("openpyxl"), "Full Excel dependencies unavailable")
    def test_changed_workbooks_merge_to_json_with_provenance(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as tmp:
            repo, output = self.make_government(tmp)
            pd.DataFrame([{"标题": "旧记录"}]).to_excel(repo / "xls_files" / "old.xlsx", index=False)
            before = runner._excel_snapshot(repo)
            for name in ["first", "second"]:
                pd.DataFrame([{"标题": name}]).to_excel(repo / "xls_files" / (name + ".xlsx"), index=False)
            files = runner._export_latest_excel(repo, output, "json", before=before)
            rows = json.loads(Path(files[0]).read_text(encoding="utf-8"))
            self.assertEqual({row["标题"] for row in rows}, {"first", "second"})
            self.assertEqual({row["来源工作簿"] for row in rows}, {"first.xlsx", "second.xlsx"})

    def test_crawl4ai_outcomes_reflect_page_failures(self):
        for flags, status in [([True, True], "completed"), ([True, False], "partial"), ([False, False], "failed")]:
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as tmp:
                rows = [{"url": f"https://example.com/{i}", "success": success,
                         "error": "" if success else "unavailable"} for i, success in enumerate(flags)]
                args = types.SimpleNamespace(url=[row["url"] for row in rows], schema=None, delivery="json")
                with patch.object(runner, "_python_stdin", return_value=json.dumps(rows)):
                    result = runner._run_crawl4ai({}, args, Path(tmp))
                self.assertEqual(result["status"], status)
                self.assertEqual(result["success_count"], sum(flags))
                self.assertEqual(result["failure_count"], len(flags) - sum(flags))
                self.assertEqual(json.loads(Path(result["files"][0]).read_text()), rows)

    def test_newsplease_outcomes_reflect_missing_articles(self):
        for rows, status, successes in [
            ([{"url": "https://example.com/a", "title": "A"}], "completed", 1),
            ([{"url": "https://example.com/a", "title": "A"}, {"url": "https://example.com/b", "error": "extract failed"}], "partial", 1),
            ([{"url": "https://example.com/b", "error": "extract failed"}], "failed", 0),
        ]:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                args = types.SimpleNamespace(url=[row["url"] for row in rows], delivery="json")
                with patch.object(runner, "_python_stdin", return_value=json.dumps(rows)):
                    result = runner._run_news_please({}, args, Path(tmp))
                self.assertEqual(result["status"], status)
                self.assertEqual(result["success_count"], successes)
                self.assertEqual(result["failure_count"], len(rows) - successes)

    def test_feapder_does_not_invent_verified_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "spider.py"
            script.write_text("", encoding="utf-8")
            with patch.object(runner, "_subprocess"):
                result = runner._run_feapder({}, types.SimpleNamespace(spider=str(script)), Path(tmp))
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["files"], [])
            self.assertTrue(result["external_output"])

    def test_no_output_file_cannot_be_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = runner._rows_result([{"url": "https://example.com"}], Path(tmp) / "absent.json")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["files"], [])

    def test_process_timeout_is_bounded_and_overrideable(self):
        completed = types.SimpleNamespace(returncode=0, stdout='{"ok": true}\n', stderr="")
        with patch.dict(os.environ, {"SCRAPING_PROCESS_TIMEOUT": "23"}), \
                patch.object(runner.subprocess, "run", return_value=completed) as mocked:
            runner._subprocess(["python", "job.py"], ROOT)
            self.assertEqual(mocked.call_args.kwargs["timeout"], 23)
            self.assertIs(mocked.call_args.kwargs["stdout"], sys.stderr)
            runner._python_stdin("print('{}')", timeout=41)
            self.assertEqual(mocked.call_args.kwargs["timeout"], 41)

    def test_timeout_failures_have_actionable_error(self):
        with patch.object(runner.subprocess, "run", side_effect=subprocess.TimeoutExpired("python", 1)):
            with self.assertRaisesRegex(runner.RunError, "process-timeout"):
                runner._subprocess(["python"], ROOT, timeout=1)
            with self.assertRaisesRegex(runner.RunError, "process-timeout"):
                runner._python_stdin("pass", timeout=1)

    def test_invalid_timeout_rejected_before_process(self):
        with patch.object(runner.subprocess, "run") as mocked:
            for value in [0, -1, "bad", float("nan"), float("inf")]:
                with self.subTest(value=value), self.assertRaises(runner.RunError):
                    runner._subprocess(["python"], ROOT, timeout=value)
            mocked.assert_not_called()

    def test_catalog_defaults_to_active_interpreter_and_external_repos_override(self):
        code = "from pipeline.catalog import PYTHON, REPOS; import json; print(json.dumps([str(PYTHON), str(REPOS)]))"
        env = os.environ.copy()
        env.pop("SCRAPING_PYTHON", None)
        env["SCRAPING_REPOS"] = str(ROOT / "external-repos")
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        python_path, repo_path = json.loads(result.stdout)
        self.assertEqual(Path(python_path), Path(sys.executable))
        self.assertEqual(Path(repo_path), (ROOT / "external-repos").resolve())

    def test_runtime_path_uses_platform_separator(self):
        with patch.dict(os.environ, {"PATH": "tail"}):
            value = catalog.runtime_env()["PATH"]
        self.assertTrue(value.startswith(str(catalog.ENV_PREFIX) + os.pathsep))
        self.assertTrue(value.endswith(os.pathsep + "tail"))

    @unittest.skipUnless(shutil.which("powershell") or shutil.which("pwsh"), "PowerShell unavailable")
    def test_launcher_restores_environment_and_working_directory(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        code = "$env:SCRAPING_PYTHON = " + quote(sys.executable) + "\n" + """
$beforePath = $env:PATH
$beforeConda = $env:CONDA_PREFIX
$beforeEncoding = $env:PYTHONIOENCODING
$beforePython = $env:SCRAPING_PYTHON
$beforeCwd = (Get-Location).Path
""" + "& " + quote(ROOT / "run-local.ps1") + " --help | Out-Null\n" + """
if ($LASTEXITCODE -ne 0) { throw 'Launcher failed' }
if (($env:PATH -ne $beforePath) -or ($env:CONDA_PREFIX -ne $beforeConda) -or ($env:PYTHONIOENCODING -ne $beforeEncoding) -or ($env:SCRAPING_PYTHON -ne $beforePython) -or ((Get-Location).Path -ne $beforeCwd)) { throw 'Caller environment changed' }
Write-Output 'RESTORED'
"""
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", code],
                                    cwd=tmp, capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESTORED", result.stdout)

    @unittest.skipUnless(shutil.which("powershell") or shutil.which("pwsh"), "PowerShell unavailable")
    def test_launcher_uses_local_runtime_config_without_caller_configuration(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            shutil.copyfile(ROOT / "run-local.ps1", folder / "run-local.ps1")
            (folder / ".runtime.json").write_text(json.dumps({"python": sys.executable}), encoding="utf-8")
            (folder / "pipeline").mkdir()
            (folder / "pipeline" / "__main__.py").write_text("print('RUNTIME_CONFIG_USED')", encoding="utf-8")
            env = os.environ.copy()
            env.pop("SCRAPING_PYTHON", None)
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                     str(folder / "run-local.ps1")], cwd=folder, env=env,
                                    capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RUNTIME_CONFIG_USED", result.stdout)

    @unittest.skipUnless(shutil.which("powershell") or shutil.which("pwsh"), "PowerShell unavailable")
    def test_full_install_fails_preflight_before_installing_missing_repositories(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                     str(ROOT / "scripts" / "install.ps1"), "-Profile", "full", "-Python", sys.executable,
                                     "-ReposRoot", str(Path(tmp) / "missing")],
                                    cwd=tmp, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Required local repositories are missing", result.stderr)
        self.assertNotIn("INSTALL_DONE", result.stdout)

    @unittest.skipUnless(os.name == "nt" and (shutil.which("powershell") or shutil.which("pwsh")), "Windows PowerShell unavailable")
    def test_research_installer_records_runtime_and_does_not_install_browser_implicitly(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "scripts").mkdir()
            shutil.copyfile(ROOT / "scripts" / "install.ps1", folder / "scripts" / "install.ps1")
            (folder / "requirements-research.txt").write_text("# fixture\n", encoding="utf-8")
            fake_python = folder / "fake-python.cmd"
            fake_python.write_text('@echo off\necho %*>>"%~dp0calls.txt"\nexit /b 0\n', encoding="ascii")
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                     str(folder / "scripts" / "install.ps1"), "-Profile", "research", "-Python", str(fake_python)],
                                    cwd=folder, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            runtime = json.loads((folder / ".runtime.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(Path(runtime["python"]), fake_python)
            calls = (folder / "calls.txt").read_text().splitlines()
            self.assertEqual(len(calls), 1)
            self.assertIn("pip install", calls[0])
            self.assertNotIn("playwright", calls[0])
            self.assertIn("INSTALL_DONE", result.stdout)


if __name__ == "__main__":
    unittest.main()
