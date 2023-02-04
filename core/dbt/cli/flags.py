# TODO  Move this to /core/dbt/flags.py when we're ready to break things
import os
import sys
from dataclasses import dataclass
from importlib import import_module
from multiprocessing import get_context
from pprint import pformat as pf
from typing import Set, List

from click import Context, get_current_context, BadOptionUsage, Command
from click.core import ParameterSource

from dbt.config.profile import read_user_config
from dbt.contracts.project import UserConfig
import dbt.cli.params as p

if os.name != "nt":
    # https://bugs.python.org/issue41567
    import multiprocessing.popen_spawn_posix  # type: ignore  # noqa: F401


@dataclass(frozen=True)
class Flags:
    def __init__(self, ctx: Context = None, user_config: UserConfig = None) -> None:

        if ctx is None:
            try:
                ctx = get_current_context()
            except Exception:
                return None

        def assign_params(ctx, params_assigned_from_default):
            """Recursively adds all click params to flag object"""
            for param_name, param_value in ctx.params.items():
                # N.B. You have to use the base MRO method (object.__setattr__) to set attributes
                # when using frozen dataclasses.
                # https://docs.python.org/3/library/dataclasses.html#frozen-instances
                object.__setattr__(self, param_name.upper(), param_value)
                if ctx.get_parameter_source(param_name) == ParameterSource.DEFAULT:
                    params_assigned_from_default.add(param_name)
            if ctx.parent:
                assign_params(ctx.parent, params_assigned_from_default)

        params_assigned_from_default = set()  # type: Set[str]
        assign_params(ctx, params_assigned_from_default)

        # Get the invoked command flags
        invoked_subcommand_name = (
            ctx.invoked_subcommand if hasattr(ctx, "invoked_subcommand") else None
        )
        if invoked_subcommand_name is not None:
            invoked_subcommand = getattr(import_module("dbt.cli.main"), invoked_subcommand_name)
            invoked_subcommand.allow_extra_args = True
            invoked_subcommand.ignore_unknown_options = True
            invoked_subcommand_ctx = invoked_subcommand.make_context(None, sys.argv)
            assign_params(invoked_subcommand_ctx, params_assigned_from_default)

        if not user_config:
            profiles_dir = getattr(self, "PROFILES_DIR", None)
            user_config = read_user_config(profiles_dir) if profiles_dir else None

        # Overwrite default assignments with user config if available
        if user_config:
            param_assigned_from_default_copy = params_assigned_from_default.copy()
            for param_assigned_from_default in params_assigned_from_default:
                user_config_param_value = getattr(user_config, param_assigned_from_default, None)
                if user_config_param_value is not None:
                    object.__setattr__(
                        self, param_assigned_from_default.upper(), user_config_param_value
                    )
                    param_assigned_from_default_copy.remove(param_assigned_from_default)
            params_assigned_from_default = param_assigned_from_default_copy

        # Hard coded flags
        object.__setattr__(self, "WHICH", invoked_subcommand_name or ctx.info_name)
        object.__setattr__(self, "MP_CONTEXT", get_context("spawn"))

        # Support console DO NOT TRACK initiave
        object.__setattr__(
            self,
            "ANONYMOUS_USAGE_STATS",
            False
            if os.getenv("DO_NOT_TRACK", "").lower() in ("1", "t", "true", "y", "yes")
            else True,
        )
        # Check mutual exclusivity once all flags are set
        self._assert_mutually_exclusive(
            params_assigned_from_default, ["WARN_ERROR", "WARN_ERROR_OPTIONS"]
        )

        # Support lower cased access for legacy code
        params = set(
            x for x in dir(self) if not callable(getattr(self, x)) and not x.startswith("__")
        )
        for param in params:
            object.__setattr__(self, param.lower(), getattr(self, param))

    def __str__(self) -> str:
        return str(pf(self.__dict__))

    def __getattribute__(self, name):
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            self.get_default(name)

    def _assert_mutually_exclusive(
        self, params_assigned_from_default: Set[str], group: List[str]
    ) -> None:
        """
        Ensure no elements from group are simultaneously provided by a user, as inferred from params_assigned_from_default.
        Raises click.UsageError if any two elements from group are simultaneously provided by a user.
        """
        set_flag = None
        for flag in group:
            flag_set_by_user = flag.lower() not in params_assigned_from_default
            if flag_set_by_user and set_flag:
                raise BadOptionUsage(
                    flag.lower(), f"{flag.lower()}: not allowed with argument {set_flag.lower()}"
                )
            elif flag_set_by_user:
                set_flag = flag

    @staticmethod
    def get_default(param_name: str):
        param_name = param_name.lower()

        try:
            param_decorator = getattr(p, param_name)
        except ImportError:
            raise AttributeError

        command = param_decorator(Command(None))
        param = command.params[0]
        default = param.default
        if callable(default):
            return default()
        else:
            if param.type:
                try:
                    return param.type.convert(default, param, None)
                except TypeError:
                    return default
            return default
