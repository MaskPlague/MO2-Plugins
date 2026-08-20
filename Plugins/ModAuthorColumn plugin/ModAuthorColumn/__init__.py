import os
import site
from typing import List

site.addsitedir(os.path.join(os.path.dirname(__file__), "lib"))

from mobase import IPluginTool #type: ignore
from .ModAuthorColumn import ModAuthorColumn

def createPlugins() -> List["IPluginTool"]:
    return [ModAuthorColumn()]