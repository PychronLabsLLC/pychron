# ===============================================================================
# Copyright 2015 Jake Ross
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

# ============= enthought library imports =======================
from envisage.ui.tasks.preferences_pane import PreferencesPane
from traits.api import Str, Bool, Int, Directory, Enum, File
from traitsui.api import View, Item, HGroup, VGroup, ObjectColumn

from pychron.core.helpers.strtools import to_bool
from pychron.core.pychron_traits import BorderVGroup
from pychron.database.tasks.connection_preferences import (
    ConnectionPreferences,
    ConnectionPreferencesPane,
    ConnectionFavoriteItem,
)
from pychron.envisage.tasks.base_preferences_helper import BasePreferencesHelper


class DVCConnectionItem(ConnectionFavoriteItem):
    organization = Str
    meta_repo_name = Str
    meta_repo_dir = Directory
    repository_root = Directory
    connection_method = Enum("direct", "cloudsql_iam")
    cloudsql_instance_connection_name = Str
    cloudsql_ip_type = Enum("public", "private", "psc")
    cloudsql_service_account_email = Str
    cloudsql_service_account_key_path = File
    attributes = (
        "name",
        "kind",
        "username",
        "host",
        "dbname",
        "password",
        "enabled",
        "default",
        "path",
        "organization",
        "meta_repo_name",
        "meta_repo_dir",
        "timeout",
        "repository_root",
        "connection_method",
        "cloudsql_instance_connection_name",
        "cloudsql_ip_type",
        "cloudsql_service_account_email",
        "cloudsql_service_account_key_path",
    )

    def __init__(self, schema_identifier="", attrs=None, load_names=False) -> None:
        super(ConnectionFavoriteItem, self).__init__()
        self.schema_identifier = schema_identifier

        if attrs:
            for attr, value in zip(self.attributes, attrs.split(",")):
                if attr in ("enabled", "default"):
                    value = to_bool(value)
                elif attr == "timeout":
                    value = int(value) if value else self.timeout
                elif attr == "kind" and value == "postgres":
                    value = "postgresql"

                setattr(self, attr, value)

            if load_names:
                self.load_names()


class DVCConnectionPreferences(ConnectionPreferences):
    preferences_path = "pychron.dvc.connection"
    _adapter_klass = "pychron.dvc.dvc_database.DVCDatabase"
    _schema_identifier = "AnalysisTbl"
    _fav_klass = DVCConnectionItem


class DVCConnectionPreferencesPane(ConnectionPreferencesPane):
    model_factory = DVCConnectionPreferences
    category = "DVC"

    def get_columns(self) -> list:
        cols = super(DVCConnectionPreferencesPane, self).get_columns()
        cols.insert(3, ObjectColumn(name="connection_method", label="Method"))
        return cols

    def traits_view(self) -> View:
        ev = View(
            VGroup(
                Item("organization"),
                Item("meta_repo_name", label="MetaData Name"),
                Item("meta_repo_dir", label="MetaData Directory"),
                Item("repository_root", label="Repository Directory"),
                VGroup(
                    Item("connection_method", label="Connection Method"),
                    Item(
                        "cloudsql_instance_connection_name",
                        label="Instance Connection Name",
                        enabled_when='connection_method=="cloudsql_iam"',
                    ),
                    Item(
                        "cloudsql_ip_type",
                        label="IP Type",
                        enabled_when='connection_method=="cloudsql_iam"',
                    ),
                    Item(
                        "cloudsql_service_account_email",
                        label="Service Account Email",
                        enabled_when='connection_method=="cloudsql_iam"',
                    ),
                    Item(
                        "cloudsql_service_account_key_path",
                        label="Service Account Key",
                        enabled_when='connection_method=="cloudsql_iam"',
                    ),
                    show_border=True,
                    label="CloudSQL IAM",
                ),
            ),
        )
        fav_grp = self.get_fav_group(edit_view=ev)

        return View(fav_grp)


class DVCPreferences(BasePreferencesHelper):
    preferences_path = "pychron.dvc"
    use_cocktail_irradiation = Bool
    use_cache = Bool
    max_cache_size = Int
    update_currents_enabled = Bool
    use_auto_pull = Bool(True)
    use_auto_push = Bool(False)
    use_default_commit_author = Bool(False)


class DVCPreferencesPane(PreferencesPane):
    model_factory = DVCPreferences
    category = "DVC"

    def traits_view(self):
        v = View(
            VGroup(
                BorderVGroup(
                    Item(
                        "use_cocktail_irradiation",
                        tooltip="Use the special cocktail.json for defining the "
                        "irradiation flux and chronology",
                        label="Use Cocktail Irradiation",
                    )
                ),
                BorderVGroup(
                    Item(
                        "use_auto_pull",
                        label="Auto Pull",
                        tooltip="If selected, automatically "
                        "update your version to the "
                        "latest version. Deselect if "
                        "you want to be asked to pull "
                        "the official version.",
                    ),
                    Item(
                        "use_auto_push",
                        label="Auto Push",
                        tooltip="Push changes when a PushNode is used automatically without asking "
                        "for confirmation.",
                    ),
                ),
                BorderVGroup(
                    Item("use_default_commit_author", label="Use Default Commit Author"),
                    label="Commit",
                ),
                BorderVGroup(
                    Item("update_currents_enabled", label="Enabled"),
                    label="Current Values",
                ),
                BorderVGroup(
                    HGroup(
                        Item("use_cache", label="Enabled"),
                        Item("max_cache_size", label="Max Size"),
                    ),
                    label="Cache",
                ),
            )
        )
        return v


class DVCExperimentPreferences(BasePreferencesHelper):
    preferences_path = "pychron.dvc.experiment"
    use_dvc_persistence = Bool
    dvc_save_timeout_minutes = Int
    use_dvc_overlap_save = Bool


class DVCExperimentPreferencesPane(PreferencesPane):
    model_factory = DVCExperimentPreferences
    category = "Experiment"

    def traits_view(self):
        v = View(
            BorderVGroup(
                Item("use_dvc_persistence", label="Use DVC Persistence"),
                Item("use_dvc_overlap_save", label="Use DVC Overlap Save"),
                Item(
                    "dvc_save_timeout_minutes",
                    label="DVC Save timeout (minutes)",
                    enabled_when="use_dvc_overlap_save",
                ),
                label="DVC",
            )
        )
        return v


class DVCRepositoryPreferences(BasePreferencesHelper):
    preferences_path = "pychron.dvc.repository"
    check_for_changes = Bool
    auto_fetch = Bool


class DVCRepositoryPreferencesPane(PreferencesPane):
    model_factory = DVCRepositoryPreferences
    category = "Repositories"

    def traits_view(self):
        v = View(
            BorderVGroup(
                Item("check_for_changes", label="Check for Changes"),
                Item(
                    "auto_fetch",
                    label="Auto Fetch",
                    tooltip='Automatically "fetch" when a local repository is selected. Turn this off '
                    "if fetching speed is an issue",
                ),
                label="",
            )
        )
        return v


# ============= EOF =============================================
