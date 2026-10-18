"""config.toml: defaults, overrides, and bad values.
    uv run pytest
"""
import os, sys
import pytest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path: sys.path.insert(0, ROOT)
from app import config


def test_keep_days_defaults_to_7_and_reads_the_file(tmp_path):
    p = tmp_path / 'config.toml'
    assert config.image_keep_days(str(p)) == 7                                   # no file
    p.write_text('[images]\nkeep_days = 30\n', encoding='utf-8')
    assert config.image_keep_days(str(p)) == 30
    p.write_text('# nothing set\n', encoding='utf-8')
    assert config.image_keep_days(str(p)) == 7


@pytest.mark.parametrize('text', ['[images]\nkeep_days = 0\n', '[images]\nkeep_days = "30"\n', '[images]\nkeep_dayz = 30\n',
                                  '[image]\nkeep_days = 30\n', '[images\n'])
def test_a_bad_setting_stops_with_a_message(tmp_path, text):
    p = tmp_path / 'config.toml'; p.write_text(text, encoding='utf-8')
    with pytest.raises(SystemExit):
        config.image_keep_days(str(p))


def test_the_example_file_holds_the_defaults():
    assert config.load(os.path.join(ROOT, 'config.example.toml')) == config.DEFAULTS
