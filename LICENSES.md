# Third-party licences

Every library this project installs, and the licence it ships under, as
read from each package's installed distribution metadata (`pip-licenses`,
cross-checked against each package's own `License-Expression`/`Classifier`
metadata). All are open source; no closed-source or paid dependency is
used anywhere in this project.

## Direct dependencies (pinned in `requirements.txt`)

| Library | Pinned version | Licence | Used for |
|---|---|---|---|
| [streamlit](https://streamlit.io) | 1.64.0 | Apache-2.0 | The dashboard UI |
| [duckdb](https://pypi.org/project/duckdb/) | 1.5.5 | MIT | Reading the vendored reconciliation database (read-only) |
| [pytest](https://docs.pytest.org/) | 9.1.1 | MIT | Test suite |

## Transitive dependencies (not pinned; versions from a clean install)

Pulled in by `streamlit` unless noted. Versions are what a clean
`pip install -r requirements.txt` resolved on 2026-09-27.

| Library | Resolved version | Licence | Pulled in by |
|---|---|---|---|
| altair | 6.3.0 | BSD-3-Clause | streamlit (charting) |
| Jinja2 | 3.1.6 | BSD-3-Clause | streamlit |
| MarkupSafe | 3.0.3 | BSD-3-Clause | Jinja2 |
| Pygments | 2.21.0 | BSD-2-Clause | pytest |
| anyio | 4.15.1 | MIT | streamlit |
| attrs | 26.1.0 | MIT | jsonschema |
| certifi | 2026.7.22 | MPL-2.0 | requests |
| charset-normalizer | 3.5.1 | MIT | requests |
| click | 8.5.0 | BSD-3-Clause | streamlit |
| h11 | 0.16.0 | MIT | uvicorn |
| httptools | 0.8.0 | MIT | uvicorn |
| idna | 3.20 | BSD-3-Clause | requests |
| iniconfig | 2.3.0 | MIT | pytest |
| itsdangerous | 2.2.0 | BSD-3-Clause | streamlit |
| jsonschema | 4.26.0 | MIT | altair |
| jsonschema-specifications | 2025.9.1 | MIT | jsonschema |
| narwhals | 2.26.0 | MIT | altair |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | pandas / pydeck |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | pytest / streamlit |
| pandas | 3.0.6 | BSD-3-Clause | streamlit |
| pillow | 12.3.0 | MIT-CMU | streamlit |
| pluggy | 1.6.0 | MIT | pytest |
| protobuf | 7.36.2 | BSD-3-Clause | streamlit |
| pyarrow | 25.0.1 | Apache-2.0 | streamlit |
| pydeck | 0.9.3 | Apache-2.0 | streamlit |
| python-dateutil | 2.9.0.post0 | Apache-2.0 OR BSD-3-Clause | pandas |
| python-multipart | 0.0.32 | Apache-2.0 | streamlit |
| referencing | 0.37.0 | MIT | jsonschema |
| requests | 2.34.2 | Apache-2.0 | streamlit |
| rpds-py | 2026.6.3 | MIT | jsonschema |
| six | 1.17.0 | MIT | python-dateutil |
| starlette | 1.7.0 | BSD-3-Clause | streamlit |
| toml | 0.10.2 | MIT | streamlit |
| typing_extensions | 4.16.0 | PSF-2.0 | streamlit / altair |
| urllib3 | 2.8.0 | MIT | requests |
| uvicorn | 0.54.0 | BSD-3-Clause | streamlit |
| watchdog | 6.0.0 | Apache-2.0 | streamlit |
| websockets | 16.1.1 | BSD-3-Clause | streamlit |

## Notices

These licences require their copyright and licence notices to be kept with
any copy or redistribution. This repository does not vendor or redistribute
any of these packages; they are installed from PyPI. Each installed package
carries its own licence and notice files, and those must be preserved in
any distribution that includes them.

No paid or closed-source service is used anywhere in this project's own
code, tests, or runtime dependencies. Any screenshots of this dashboard
were taken locally with an ordinary browser, outside this repo; that is
not part of the demo and involves no dependency listed here.
