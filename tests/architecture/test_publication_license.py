import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PublicationLicenseTests(unittest.TestCase):
    def test_license_is_research_only_with_no_personal_live_trading_exception(self):
        text = (ROOT / "LICENSE").read_text()
        for required in ("LicenseRef-BYQ-Individual-Noncommercial-1.0", "不是 OSI", "不允许实盘交易",
                         "个人使用自有资金", "非营利", "商业授权", "第三方原有许可证", "强制性责任"):
            self.assertIn(required, text)
        self.assertNotIn("个人自有资金投资的有限例外", text)
        self.assertNotIn("第 3 条是个人投资收益的明确例外", text)
        self.assertIn("人工下单、外接脚本/券商接口、复制输出、第三方执行或修改软件，不构成例外", text)
        self.assertIn("禁止机构使用及禁止实盘限制", text)
        self.assertIn("这些措施不构成实盘使用许可", text)
        self.assertIn("故意规避第 3 或第 4 条", text)

    def test_risk_notice_is_prominent_and_rights_are_not_implicitly_transferred(self):
        readme = (ROOT / "README.md").read_text()
        self.assertLess(readme.index("禁止机构使用"), readme.index("当前已完成"))
        self.assertIn("不得免责", readme)
        cla = (ROOT / "CONTRIBUTOR_LICENSE_AGREEMENT.md").read_text()
        for required in ("不是版权转让", "商业使用", "再许可", "HEAD:", "AGREEMENT-SHA256:",
                         "不能由贡献者", "不追溯推定", "机构拥有的成果"):
            self.assertIn(required, cla)
        for name in ("CONTRIBUTING.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md", "docs/legal/OWNERSHIP.md"):
            self.assertTrue((ROOT / name).is_file())

    def test_declaration_inventory_is_current(self):
        result = subprocess.run(["python3", "scripts/ci/license-inventory.py", "--check"], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        inventory = json.loads((ROOT / "docs/legal/npm-license-inventory.json").read_text())
        self.assertGreater(len(inventory["packages"]), 500)

    def test_dsh_u5_progress_does_not_claim_withdrawn_qualification(self):
        text = (ROOT / "docs/roadmap/DSH_012RC1_EXECUTION.md").read_text()
        evidence_root = ROOT / "docs/evidence/dsh-012rc1/u5"
        withdrawn = json.loads((evidence_root / "withdrawn/qualification-report.withdrawn.json").read_text())
        failure = json.loads((evidence_root / "withdrawn/qualification-evidence.isolation-failure.json").read_text())
        restored = json.loads((evidence_root / "report-preproduction-remediated/qualification-report.json").read_text())
        self.assertEqual(withdrawn["qualification_state"], "WITHDRAWN")
        self.assertEqual(failure["checks"][34]["result"], "FAIL")
        self.assertEqual(failure["checks"][35]["result"], "BLOCKED")
        self.assertEqual(restored["qualification_state"], "QUALIFIED")
        self.assertEqual(restored["qualification_scope"], "preproduction")
        self.assertTrue(all(row["result"] == "PASS" for row in restored["checks"][:37]))
        self.assertTrue(all(row["result"] == "NOT_RUN" for row in restored["checks"][37:]))
        self.assertIn("report-preproduction-remediated/qualification-report.json", text)
        self.assertIn("U1–U8 串行开发", text)
        self.assertIn("0.1.1rc1", text)
        self.assertIn("U0 载体决策 | MERGED", text)
        self.assertIn("不宣称正式切换、生产部署或生产观察", text)
        adr = (ROOT / "docs/architecture/adr/ADR-0058-dsh-release-bundles-and-compatibility.md").read_text()
        self.assertIn("Status: Accepted", adr)
        self.assertIn("仍不包含生产部署、正式版本切换或付费模型测试", adr)
