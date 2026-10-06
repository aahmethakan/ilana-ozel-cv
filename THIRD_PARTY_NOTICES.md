# Third-party notices

This is a verified index of the pinned direct dependencies for
`Ilana Ozel CV v0.1.0-rc.1`. It is not legal advice and does not replace the
license texts and notices in the resolved distributions. A deployment or
redistribution process must preserve the applicable upstream notices for the
exact wheels and source artifacts it ships.

## Production dependencies

| Package | Version | Declared upstream license | Upstream license/source |
| --- | ---: | --- | --- |
| FastAPI | 0.141.1 | MIT | https://github.com/fastapi/fastapi/blob/master/LICENSE |
| Uvicorn | 0.52.4 | BSD-3-Clause | https://github.com/Kludex/uvicorn/blob/master/LICENSE.md |
| Pydantic | 2.13.5 | MIT | https://github.com/pydantic/pydantic/blob/main/LICENSE |
| pydantic-settings | 2.15.0 | MIT | https://github.com/pydantic/pydantic-settings/blob/main/LICENSE |
| PyMuPDF | 1.28.2 | GNU AGPL v3 or Artifex commercial license | https://pymupdf.readthedocs.io/en/latest/about.html |
| python-multipart | 0.0.32 | Apache License 2.0 | https://github.com/Kludex/python-multipart/blob/master/LICENSE.txt |
| OpenAI Python SDK | 3.13.0 | Apache License 2.0 | https://github.com/openai/openai-python/blob/main/LICENSE |
| python-docx | 1.2.0 | MIT | https://github.com/python-openxml/python-docx/blob/master/LICENSE |

## Development and test dependencies

| Package | Version | Declared upstream license | Upstream license/source |
| --- | ---: | --- | --- |
| pytest | 9.1.1 | MIT | https://github.com/pytest-dev/pytest/blob/main/LICENSE |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx/blob/master/LICENSE.md |

## PyMuPDF and MuPDF

The production dependency is `pymupdf==1.28.2`. The installed package metadata
declares it dual-licensed under GNU AGPL 3.0 or an Artifex commercial license.
The application retains the GNU AGPLv3 path. At runtime, PyMuPDF reports
embedded MuPDF version `1.28.2`.

PyMuPDF/MuPDF and any components carried in the selected upstream distribution
require release-owner review of the exact artifact's COPYING/license/notice
materials. Do not remove or replace upstream attribution and license material
when publishing source or redistributing an artifact.
