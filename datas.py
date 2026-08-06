import dataclasses
from typing import ClassVar, Optional


def asdict(data_class) -> dict:
    return dataclasses.asdict(data_class)


@dataclasses.dataclass
class Prefs:
    debug_value: int
    binary_path: str
    addon_dir: str
    addon_module_name: str
    app_id: int
    download_counter: int
    asset_popup_counter: int
    welcome_operator_counter: int
    api_key: str
    api_key_refresh: str
    api_key_timeout: int
    experimental_features: bool
    keep_preferences: bool
    directory_behaviour: str
    global_dir: str
    project_subdir: str
    unpack_files: bool
    create_asset_library: bool
    show_on_start: bool
    thumb_size: int
    maximized_assetbar_rows: int
    assetbar_expanded: bool
    search_field_width: int
    search_in_header: bool
    tips_on_start: bool
    announcements_on_start: bool
    assetbar_follows_cursor: bool
    proxor_enabled: bool
    client_port: str
    ip_version: str
    ssl_context: str
    proxy_which: str
    proxy_address: str
    trusted_ca_certs: str
    auto_check_update: bool
    enable_prereleases: bool
    updater_interval_months: int
    updater_interval_days: int
    resolution: str
    material_import_automap: bool


@dataclasses.dataclass
class SearchData:
    """Data needed to make a Search request."""

    PREFS: Prefs
    tempdir: str
    urlquery: str
    asset_type: str
    scene_uuid: str
    get_next: bool
    page_size: int
    blender_version: str
    addon_version: str = ""
    platform_version: str = ""
    api_key: str = ""
    app_id: int = 0
    is_validator: bool = (
        False  # Client makes some extra stuff for validators - like fetching all the ratings right away
    )
    history_id: str = ""
    search_order_by: str = (
        "default"  # mirrors ui_props.search_order_by; used for client-side post-sort
    )


@dataclasses.dataclass
class SocialNetwork:
    url: str
    icon: str
    name: str
    order: int


def parse_social_networks(networks: list[dict]) -> list[SocialNetwork]:
    social_networks = []
    for network in networks:
        url = network.get("url", "")
        n = network.get("socialNetwork", {})
        social_network = SocialNetwork(
            url=url,
            icon=n.get("icon", ""),
            name=n.get("name", ""),
            order=n.get("order", -1),
        )
        social_networks.append(social_network)
    return social_networks


def _parse_social_networks_lenient(value):
    """Parse raw socialNetworks dicts, but pass already-parsed lists through."""
    if value and isinstance(value[0], dict):
        return parse_social_networks(value)
    return value


class FromDictMixin:
    """Gives a dataclass a lenient ``from_dict`` constructor.

    Unknown keys in the source dict are ignored so the addon keeps working when
    the server adds new fields (older addons must not crash). Subclasses may set
    ``_FIELD_PARSERS`` (name -> callable) to transform raw values, e.g. to build
    nested dataclasses, before construction. Requires all fields to have
    defaults so that omitted server fields don't raise either.
    """

    _FIELD_PARSERS: ClassVar[dict] = {}

    @classmethod
    def from_dict(cls, data: dict):
        field_names = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
        known = {k: v for k, v in data.items() if k in field_names}
        for name, parser in cls._FIELD_PARSERS.items():
            if name in known:
                known[name] = parser(known[name])
        return cls(**known)


@dataclasses.dataclass
class UserProfile(FromDictMixin):
    """This is public information about profiles of others.

    All fields have defaults so that the addon keeps working when the server
    adds or omits fields; use ``from_dict`` to build from raw API data safely.
    """

    aboutMe: str = ""
    aboutMeUrl: str = ""
    avatar128: str = ""
    firstName: str = ""
    fullName: str = ""
    gravatarHash: str = ""
    id: int = -1
    lastName: str = ""
    socialNetworks: list[SocialNetwork] = dataclasses.field(default_factory=list)
    avatar256: str = ""
    avatar512: str = ""
    gravatarImg: str = ""  # filled later from getGravatar task
    tooltip: str = ""  # generated later from Name and AboutMe etc.

    _FIELD_PARSERS = {"socialNetworks": _parse_social_networks_lenient}


@dataclasses.dataclass
class MineProfile(FromDictMixin):
    """
    This is private information about current user's profile. Fields can be also None.
    Because API can just return null just for fun (https://github.com/BlenderKit/BlenderKit/issues/1545#event-17220997340).
    None/null is not 0 or "" however, so we keep the None to distinguish both states.
    As result the Nones has to be captured later in code, types are just hints in here!
    """

    aboutMe: str = ""
    aboutMeUrl: str = ""
    avatar128: str = ""
    avatar256: str = ""
    avatar512: str = ""
    currentPlanName: str = ""
    email: str = ""
    firstName: str = ""
    fullName: str = ""
    gravatarHash: str = ""
    hasFreePlan: bool = True
    id: int = -1
    lastName: str = ""
    remainingPrivateQuota: int = 0
    sumAssetFilesSize: int = 0
    sumPrivateAssetFilesSize: int = 0
    username: str = ""
    socialNetworks: list[SocialNetwork] = dataclasses.field(default_factory=list)
    gravatarImg: str = ""  # filled later from getGravatar task
    tooltip: str = ""  # generated later from Name and AboutMe etc.
    canEditAllAssets: bool = False  # whether User is validator

    _FIELD_PARSERS = {"socialNetworks": _parse_social_networks_lenient}

    def __bool__(self):
        return self.id != -1


@dataclasses.dataclass
class AssetRating(FromDictMixin):
    bookmarks: Optional[int] = None  # name kept as comes from API
    quality: Optional[int] = None
    quality_fetched: bool = False
    working_hours: Optional[float] = None  # name kept as comes from API
    working_hours_fetched: bool = False
    # TODO: Add last time ratings checked to improve caching
