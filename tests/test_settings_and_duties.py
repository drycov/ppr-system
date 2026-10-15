import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from cryptography.fernet import Fernet

# Keep tests isolated from a developer's local application database.
os.environ["PPR_DB_PATH"] = str(Path(tempfile.gettempdir()) / "ppr-settings-tests-unused.db")
os.environ["PPR_SETTINGS_SECRET_KEY"] = Fernet.generate_key().decode("ascii")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Department, DutySchedule, SettingsAudit, SystemSetting, User
from planning import get_duty_user
from settings_service import (
    CATALOG_BY_KEY,
    get_setting,
    get_settings_snapshot,
    save_settings,
)


class SettingsServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_defaults_are_centralized_and_not_overridden(self):
        self.assertEqual(get_setting(self.db, "planning.default_horizon_months"), 1)
        item = next(x for x in get_settings_snapshot(self.db) if x["key"] == "planning.default_horizon_months")
        self.assertFalse(item["is_overridden"])
        self.assertEqual(item["value"], 1)

    def test_save_valid_setting_persists_and_is_audited(self):
        changed = save_settings(self.db, {"planning.default_horizon_months": 6}, "tester")
        self.assertIn("planning.default_horizon_months", changed)
        self.assertEqual(get_setting(self.db, "planning.default_horizon_months"), 6)
        audit = self.db.query(SettingsAudit).one()
        self.assertEqual(audit.actor, "tester")
        self.assertEqual(audit.changes["planning.default_horizon_months"]["new"], 6)

    def test_invalid_range_and_unknown_key_are_rejected(self):
        with self.assertRaises(ValueError):
            save_settings(self.db, {"planning.default_horizon_months": 25}, "tester")
        with self.assertRaises(ValueError):
            save_settings(self.db, {"unknown.option": True}, "tester")
        self.assertEqual(self.db.query(SystemSetting).count(), 0)

    def test_secret_is_encrypted_at_rest_and_masked_in_api_and_audit(self):
        secret = "zabbix-token-do-not-leak"
        save_settings(self.db, {"integrations.zabbix.token": secret}, "tester")
        row = self.db.query(SystemSetting).filter_by(key="integrations.zabbix.token").one()
        self.assertNotEqual(row.value, secret)
        self.assertTrue(row.value.startswith("enc:v1:"))
        self.assertNotIn(secret, str(self.db.query(SettingsAudit).one().changes))
        snapshot = next(x for x in get_settings_snapshot(self.db) if x["key"] == "integrations.zabbix.token")
        self.assertEqual(snapshot["value"], "")
        self.assertTrue(snapshot["configured"])
        self.assertEqual(get_setting(self.db, "integrations.zabbix.token"), secret)

    def test_empty_secret_does_not_clear_existing_secret(self):
        save_settings(self.db, {"integrations.zabbix.token": "keep-me"}, "tester")
        save_settings(self.db, {"integrations.zabbix.token": ""}, "tester")
        self.assertEqual(get_setting(self.db, "integrations.zabbix.token"), "keep-me")


class DutyResolutionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.department_a = Department(name="ОСС")
        self.department_b = Department(name="АПК")
        self.db.add_all([self.department_a, self.department_b])
        self.db.flush()
        self.local_user = User(username="local", full_name="Локальный дежурный", department_id=self.department_a.id, is_active=True, can_duty=True)
        self.global_user = User(username="global", full_name="Общий дежурный", department_id=self.department_b.id, is_active=True, can_duty=True)
        self.db.add_all([self.local_user, self.global_user])
        self.db.flush()
        self.day = date(2026, 10, 15)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_local_department_duty_has_priority_over_global(self):
        self.db.add_all([
            DutySchedule(duty_date=self.day, department_id=None, user_id=self.global_user.id, shift="day"),
            DutySchedule(duty_date=self.day, department_id=self.department_a.id, user_id=self.local_user.id, shift="day"),
        ])
        self.db.commit()
        self.assertEqual(get_duty_user(self.db, self.day, self.department_a.id).id, self.local_user.id)

    def test_global_duty_is_fallback_when_department_has_no_assignment(self):
        self.db.add(DutySchedule(duty_date=self.day, department_id=None, user_id=self.global_user.id, shift="day"))
        self.db.commit()
        self.assertEqual(get_duty_user(self.db, self.day, self.department_a.id).id, self.global_user.id)

    def test_other_department_duty_is_not_used_as_global_fallback(self):
        self.db.add(DutySchedule(duty_date=self.day, department_id=self.department_b.id, user_id=self.global_user.id, shift="day"))
        self.db.commit()
        self.assertIsNone(get_duty_user(self.db, self.day, self.department_a.id))


if __name__ == "__main__":
    unittest.main()
