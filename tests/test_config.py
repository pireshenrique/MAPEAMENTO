import pytest
import yaml

from radar.settings import EnvSettings, load_config


def test_loads_real_config(config):
    names = [c.name for c in config.competitors]
    assert names == ["Deca", "Roca", "Celite", "Docol", "Tigre", "Kohler", "Dexco"]
    assert config.settings.collection.backfill_days == 7
    assert config.settings.ai.model
    assert "Outro" in [c.name for c in config.categories]


def test_defaults_merged_into_competitors(config):
    assert "banheiro" in config.competitor("Roca").context_terms
    assert "futebol" in config.competitor("Tigre").exclude_terms


def test_profile_only_has_given_segments(config):
    assert config.profile.name == "Lorenzetti"
    assert config.profile.segments == ["chuveiros elétricos", "metais sanitários", "louças sanitárias",
                                       "bombas hidráulicas", "purificadores", "aquecedores a gás"]
    assert config.profile.products == [] and config.profile.competitors_by_category == {}


def test_env_secrets_not_in_yaml():
    from pathlib import Path
    for f in Path("config").glob("*.yaml"):
        assert "api_key" not in f.read_text().lower()


def test_env_vars(monkeypatch):
    monkeypatch.setenv("NEWS_API_KEY", "abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///x.db")
    env = EnvSettings(_env_file=None)
    assert env.news_api_key == "abc" and env.database_url == "sqlite:///x.db"
    assert env.ai_provider == "anthropic"


def _write(tmp_path, competitors):
    import shutil
    for f in ("settings", "categories", "company_profile"):
        shutil.copy(f"config/{f}.yaml", tmp_path / f"{f}.yaml")
    (tmp_path / "competitors.yaml").write_text(yaml.safe_dump({"competitors": competitors}), encoding="utf-8")


def test_new_competitor_via_yaml_only(tmp_path):
    _write(tmp_path, [{"name": "Nova", "aliases": ["Nova Metais"], "domains": ["WWW.Nova.com"]}])
    cfg = load_config(tmp_path, env=EnvSettings(_env_file=None))
    assert cfg.competitors[0].domains == ["nova.com"]


def test_duplicate_competitor_rejected(tmp_path):
    c = {"name": "A", "aliases": ["A"]}
    _write(tmp_path, [c, c])
    with pytest.raises(ValueError):
        load_config(tmp_path, env=EnvSettings(_env_file=None))


def test_competitor_without_alias_rejected(tmp_path):
    _write(tmp_path, [{"name": "A"}])
    with pytest.raises(ValueError):
        load_config(tmp_path, env=EnvSettings(_env_file=None))


def test_unknown_key_rejected(tmp_path):
    _write(tmp_path, [{"name": "A", "aliases": ["A"], "typo": 1}])
    with pytest.raises(ValueError):
        load_config(tmp_path, env=EnvSettings(_env_file=None))


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path, env=EnvSettings(_env_file=None))
