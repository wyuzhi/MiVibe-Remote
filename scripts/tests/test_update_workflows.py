from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD_WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"
PROMOTE_WORKFLOW = ROOT / ".github" / "workflows" / "promote-updates.yml"


class UpdateWorkflowSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.build = BUILD_WORKFLOW.read_text(encoding="utf-8")
        cls.promote = PROMOTE_WORKFLOW.read_text(encoding="utf-8")

    def test_candidate_build_never_publishes_the_stable_feed(self) -> None:
        self.assertNotIn("publish-update-feed", self.build)
        self.assertNotIn("releases/download/update-feed", self.build)
        self.assertNotIn("aws s3 cp", self.build)
        self.assertIn(
            "building with updates safely disabled",
            self.build.lower(),
        )
        self.assertIn(
            "Private GitHub Release URLs cannot be used as the client update origin",
            self.build,
        )

    def test_stable_promotion_requires_published_or_explicit_manual_event(self) -> None:
        self.assertIn("release:\n    types:\n      - published", self.promote)
        self.assertIn("workflow_dispatch:", self.promote)
        self.assertIn("PROMOTE_STABLE", self.promote)
        self.assertIn("Draft releases cannot be promoted", self.promote)
        self.assertIn("Prereleases cannot be promoted", self.promote)
        self.assertIn("github.event.release.prerelease == false", self.promote)
        self.assertIn("startsWith(github.event.release.tag_name, 'v')", self.promote)
        self.assertIn("vars.UPDATE_BASE_URL != ''", self.promote)

    def test_external_origin_and_signing_material_are_mandatory(self) -> None:
        for setting in (
            "UPDATE_BASE_URL",
            "UPDATE_PUBLIC_KEY",
            "UPDATE_PRIVATE_KEY_BASE64",
            "UPDATE_S3_ENDPOINT",
            "UPDATE_S3_BUCKET",
            "UPDATE_S3_ACCESS_KEY_ID",
            "UPDATE_S3_SECRET_ACCESS_KEY",
        ):
            self.assertIn(setting, self.promote)
        self.assertIn(
            "A private GitHub Release cannot be the client update origin",
            self.promote,
        )

    def test_installers_are_uploaded_before_appcasts_and_archive(self) -> None:
        installer_step = self.promote.index(
            "- name: Upload immutable installers to external storage"
        )
        public_asset_verify_step = self.promote.index(
            "- name: Verify public installer bytes before changing appcasts"
        )
        appcast_step = self.promote.index("- name: Promote stable appcasts last")
        verify_step = self.promote.index("- name: Verify the promoted public appcasts")
        archive_step = self.promote.index(
            "- name: Archive promoted files in the private GitHub repository"
        )
        self.assertLess(installer_step, public_asset_verify_step)
        self.assertLess(public_asset_verify_step, appcast_step)
        self.assertLess(appcast_step, verify_step)
        self.assertLess(verify_step, archive_step)

    def test_release_asset_race_is_bounded_and_rejects_duplicates(self) -> None:
        self.assertIn("for attempt in $(seq 1 31)", self.promote)
        self.assertIn("sleep 30", self.promote)
        self.assertIn("Timed out waiting 15 minutes", self.promote)
        self.assertIn("check-release-assets", self.promote)
        self.assertIn("--pattern \"$EXPECTED_MAC_FILENAME\"", self.promote)
        self.assertIn("--pattern \"$EXPECTED_WINDOWS_FILENAME\"", self.promote)

    def test_exact_asset_versions_and_rollback_guard_run_before_upload(self) -> None:
        metadata_step = self.promote.index("expected-assets")
        rollback_step = self.promote.index(
            "- name: Reject same-version or rollback promotion"
        )
        upload_step = self.promote.index(
            "- name: Upload immutable installers to external storage"
        )
        self.assertLess(metadata_step, rollback_step)
        self.assertLess(rollback_step, upload_step)
        self.assertIn("check-upgrade", self.promote)
        self.assertIn("mac_status\" == 200", self.promote)
        self.assertIn("mac_status\" != 404", self.promote)

    def test_private_credentials_are_scoped_to_the_steps_that_need_them(self) -> None:
        job_env = self.promote.split("    steps:", 1)[0]
        self.assertNotIn("secrets.UPDATE_ED25519_PRIVATE_KEY_BASE64", job_env)
        self.assertNotIn("secrets.UPDATE_S3_ACCESS_KEY_ID", job_env)
        self.assertIn("secrets.UPDATE_ED25519_PRIVATE_KEY_BASE64", self.promote)
        self.assertIn("secrets.UPDATE_S3_ACCESS_KEY_ID", self.promote)


if __name__ == "__main__":
    unittest.main()
