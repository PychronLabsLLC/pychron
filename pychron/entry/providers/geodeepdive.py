# ===============================================================================
# Copyright 2019 ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===============================================================================
import requests

API_URL = "https://geodeepdive.org/api"


def get_snippet(term):
    s = requests.Session()
    url = "{}/snippets?term={}".format(API_URL, term)
    r = s.get(url)
    obj = r.json()

    return obj["success"]["data"]


if __name__ == "__main__":
    g = get_snippet("Fish Canyon")
    for o in g:
        print(o)

# ============= EOF =============================================
