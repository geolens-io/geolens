"""The frontend serves UTF-8 text files (llms.txt, /third-party-licenses.txt).

Without a charset on ``text/plain`` responses, browsers decode them as
Windows-1252 and show em dashes and accented names as mojibake.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"


def test_text_plain_is_served_as_utf8():
    conf = "\n".join(
        line
        for line in NGINX_CONF.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )

    assert re.search(r"^\s*charset\s+utf-8\s*;", conf, re.M)
    charset_types = re.search(r"^\s*charset_types\s+([^;]*);", conf, re.M)
    if charset_types:
        assert "text/plain" in charset_types.group(1).split()
