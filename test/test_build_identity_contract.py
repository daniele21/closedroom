from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class BuildIdentityContractTests(unittest.TestCase):
    def test_local_app_identity_is_stable_across_product_versions(self) -> None:
        build = (ROOT / "build.sh").read_text(encoding="utf-8")
        spec = (ROOT / "ClosedRoom.spec").read_text(encoding="utf-8")

        self.assertIn(
            'APP_BUNDLE_NAME="${CLOSEDROOM_APP_BUNDLE_NAME:-${APP_NAME}.app}"',
            build,
        )
        self.assertIn(
            'APP_DISPLAY_NAME="${CLOSEDROOM_APP_DISPLAY_NAME:-$APP_NAME}"',
            build,
        )
        self.assertIn('APP_PATH="$DIST_DIR/$APP_BUNDLE_NAME"', build)
        self.assertIn('CLOSEDROOM_APP_DISPLAY_NAME="$APP_DISPLAY_NAME"', build)
        self.assertNotIn('APP_BUNDLE_BASENAME="${APP_NAME}-${APP_VERSION}"', build)

        self.assertIn(
            'APP_BUNDLE_NAME = os.environ.get("CLOSEDROOM_APP_BUNDLE_NAME", f"{APP_NAME}.app")',
            spec,
        )
        self.assertIn(
            'APP_DISPLAY_NAME = os.environ.get("CLOSEDROOM_APP_DISPLAY_NAME", APP_NAME)',
            spec,
        )
        self.assertIn('"CFBundleShortVersionString": APP_VERSION', spec)
        self.assertIn('"CFBundleVersion": APP_VERSION', spec)

    def test_distribution_names_are_versioned_without_versioning_inner_app(self) -> None:
        build = (ROOT / "build.sh").read_text(encoding="utf-8")
        artifact = (ROOT / "scripts" / "build_artifact.sh").read_text(encoding="utf-8")
        production = (ROOT / "scripts" / "build_production_artifact.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('DMG_BASENAME="${APP_NAME}-${APP_VERSION}"', build)
        self.assertIn(
            'APP_BUNDLE_NAME="${CLOSEDROOM_APP_BUNDLE_NAME:-${APP_NAME}.app}"',
            artifact,
        )
        self.assertIn('STAGING_APP="$ROOT/dist/$APP_BUNDLE_NAME"', artifact)
        self.assertIn(
            'FINAL_BASENAME="${APP_NAME}-${APP_VERSION}-${BUILD_ID}-${SOURCE_REVISION}"',
            artifact,
        )
        self.assertIn(
            'app_bundle_name = os.getenv("CLOSEDROOM_APP_BUNDLE_NAME", f"{app_name}.app")',
            production,
        )
        self.assertIn('staging_app = root / "dist" / app_bundle_name', production)
        self.assertIn('env["CLOSEDROOM_APP_DISPLAY_NAME"] = app_name', production)
        self.assertIn(
            'final_basename = f"{app_name}-{version}-{build_id}-{revision[:12]}"',
            production,
        )

    def test_install_target_is_stable_and_ad_hoc_install_remains_blocked(self) -> None:
        build = (ROOT / "build.sh").read_text(encoding="utf-8")

        self.assertIn('rm -rf "/Applications/$APP_BUNDLE_NAME"', build)
        self.assertIn('ditto "$APP_PATH" "/Applications/$APP_BUNDLE_NAME"', build)
        self.assertIn("--install is not allowed with ad-hoc signing", build)
        self.assertIn("security find-identity -v -p codesigning", build)
        self.assertIn("Code-signing identity not found", build)

    def test_dmg_defaults_to_stable_app_and_canonical_product_version(self) -> None:
        create_dmg = (ROOT / "create_dmg.sh").read_text(encoding="utf-8")

        self.assertIn('scripts/product_version.py', create_dmg)
        self.assertIn('APP_PATH="${1:-$SCRIPT_DIR/dist/${APP_NAME}.app}"', create_dmg)
        self.assertIn(
            'DMG_PATH="${2:-$SCRIPT_DIR/dist/${APP_NAME}-${VERSION}.dmg}"',
            create_dmg,
        )
        self.assertNotIn("pyproject.toml", create_dmg)


if __name__ == "__main__":
    unittest.main()
