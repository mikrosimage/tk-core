# Copyright (c) 2013 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import sys

from .action_base import Action
from . import core
from ...util import shotgun
from ...errors import TankError
from ... import pipelineconfig_utils

from .setup_project_core import run_project_setup
from .setup_project_params import ProjectSetupParameters

class SetupProjectFactoryAction(Action):
    """
    Special handling of Project setup.
    
    This is a more complex alternative to the simple setup_project command.
    
    This class exposes a setup_project_factory command to the API only (no tank command support)
    which returns a factory command object which can then in turn construct project setup wizard instances which 
    can be used to build interactive wizard-style project setup processes.
    
    it is used like this:
    
    >>> import tank
    # create our factory object
    >>> factory = tank.get_command("setup_project_factory")
    # the factory can spit out set up wizards
    >>> setup_wizard = factory.execute({})
    # now set up various parameters etc on the project wizard
    # this can be an interactive process which includes validation etc. 
    >>> wizard.set_parameters(....)
    # lastly, execute the actual setup.
    >>> wizard.execute()
    
    """    
    def __init__(self):
        Action.__init__(self, 
                        "setup_project_factory", 
                        Action.GLOBAL, 
                        ("Returns a factory object which can be used to construct setup wizards. These wizards "
                         "can then be used to run an interactive setup process."), 
                        "Configuration")
        
        # no tank command support for this one because it returns an object
        self.supports_tank_command = False
        
        # this method can be executed via the API
        self.supports_api = True
        
        self.parameters = {}
                
    def run_interactive(self, log, args):
        """
        Tank command accessor
        """
        raise TankError("This Action does not support command line access")
        
    def run_noninteractive(self, log, parameters):
        """
        API accessor
        """        
        # connect to shotgun
        (sg, sg_app_store, sg_app_store_script_user) = self._shotgun_connect(log)
        # return a wizard object
        return SetupProjectWizard(log, sg, sg_app_store, sg_app_store_script_user)
                    
    def _shotgun_connect(self, log):
        """
        Connects to the App store and to the associated shotgun site.
        Logging in to the app store is optional and in the case this fails,
        the app store parameters will return None. 
        
        The method returns a tuple with three parameters:
        
        - sg is an API handle associated with the associated site
        - sg_app_store is an API handle associated with the app store
        - sg_app_store_script_user is a sg dict (with name, id and type) 
          representing the script user used to connect to the app store.
        
        :returns: (sg, sg_app_store, sg_app_store_script_user) - see above.
        """
        
        # now connect to shotgun
        try:
            log.info("Connecting to Shotgun...")
            sg = shotgun.create_sg_connection()
            sg_version = ".".join([ str(x) for x in sg.server_info["version"]])
            log.debug("Connected to target Shotgun server! (v%s)" % sg_version)
        except Exception, e:
            raise TankError("Could not connect to Shotgun server: %s" % e)
    
        try:
            log.info("Connecting to the App Store...")
            (sg_app_store, script_user) = shotgun.create_sg_app_store_connection()
            sg_version = ".".join([ str(x) for x in sg_app_store.server_info["version"]])
            log.debug("Connected to App Store! (v%s)" % sg_version)
        except Exception, e:
            log.warning("Could not establish a connection to the app store! You can "
                        "still create new projects, but you have to base them on "
                        "configurations that reside on your local disk.")
            log.debug("The following error was raised: %s" % e)
            sg_app_store = None
            script_user = None
        
        return (sg, sg_app_store, script_user)
                


class SetupProjectWizard(object):
    """
    A class which wraps around the project setup functionality in toolkit.
    """
    
    def __init__(self, log, sg, sg_app_store, sg_app_store_script_user):
        """
        Constructor. 
        """        
        self._log = log
        self._sg = sg
        self._sg_app_store = sg_app_store
        self._sg_app_store_script_user = sg_app_store_script_user
        self._params = ProjectSetupParameters(self._log, 
                                              self._sg, 
                                              self._sg_app_store, 
                                              self._sg_app_store_script_user)
                
    def set_project(self, project_id, force=False):
        """
        Specify which project that should be set up.
        
        :param project_id: Shotgun id for the project that should be set up.
        :param force: Allow for the setting up of existing projects.
        """
        self._params.set_project_id(project_id, force)     
        
    def validate_config_uri(self, config_uri):
        """
        Validates a configuration template to check if it is compatible with the current Shotgun setup.
        This will download the configuration, validate it to ensure that it is compatible with the 
        constraints (versions of core and shotgun) of this system. 
        
        If locating, downloading, or validating the configuration fails, exceptions will be raised.
        
        Once the configuration exists and is compatible, the storage situation is reviewed against shotgun.
        A dictionary with a breakdown of all storages required by the configuration is returned:
                
        {
          "primary" : { "description": "Description",
                        "exists_on_disk": False,
                        "defined_in_shotgun": True,
                        "shotgun_id": 12,
                        "darwin": "/mnt/foo",
                        "win32": "z:\mnt\foo",
                        "linux2": "/mnt/foo"},
                                    
          "textures" : { "description": None,
                         "exists_on_disk": False,
                         "defined_in_shotgun": True,
                         "shotgun_id": 14,
                         "darwin": None,
                         "win32": "z:\mnt\foo",
                         "linux2": "/mnt/foo"}                                    
        }
        
        The main dictionary is keyed by storage name. It will contain one entry
        for each local storage which is required by the configuration template.
        Each sub-dictionary in turn contains the following items:
        
        - description: Description what the storage is used for. This comes from the 
          configuration template and can be used to help a user to explain the purpose
          of a particular storage required by a configuration.
        - defined_in_shotgun: If false, no local storage with this name exists in Shotgun.
        - shotgun_id: If defined_in_shotgun is True, this will contain the entity id for
          the storage. If defined_in_shotgun is False, this will be set to none.
        - darwin/win32/linux: Paths to storages, as defined in Shotgun. These values can be
          None if a storage has not been defined.
        - exists_on_disk: Flag if the path defined for the current operating system exists on
          disk or not. 
        
        :param config_uri: Configuration uri representing the location of a config
        :returns: dictionary with storage data, see above.
        """
        return self._params.validate_config_uri(config_uri)
        
    def set_config_uri(self, config_uri):
        """
        Validate and set a configuration uri to use with this setup wizard. 
        
        In order to proceed with further functions, such as setting a project name,
        the config uri needs to be set.

        Exceptions will be raise if the configuration is not valid.
        Use the validate_config_uri() to check.

        :param config_uri: string describing a path on disk, a github uri or the name of an app store config.
        """
        self._params.set_config_uri(config_uri)

    def get_config_metadata(self):
        """
        Returns a metadata dictionary for the config that has been associated with the wizard.
        Returns a dictionary with information.
        
        :returns: dictionary with display_name and description keys
        """
        d = {}
        d["display_name"] = self._params.get_configuration_display_name()
        d["description"] = self._params.get_configuration_description()
        return d

    def get_default_project_disk_name(self):
        """
        Returns a default project name from toolkit.
        
        Before you call this method, a config and a project must have been set.
        
        This will execute hooks etc and given the selected project id will
        return a suggested project name.
        
        :returns: string with a suggested project name
        """
        return self._params.get_default_project_disk_name()
        
    def validate_project_disk_name(self, project_disk_name):
        """
        Validate the project disk name.
        Raises Exceptions if the project disk name is not valid.
        
        :param project_disk_name: string with a project name.
        """
        self._params.validate_project_disk_name(project_disk_name)
        
    def preview_project_paths(self, project_disk_name):
        """
        Return preview project paths given a project name.
        
        { "primary": { "darwin": "/foo/bar/project_name", 
                       "linux2": "/foo/bar/project_name",
                       "win32" : "c:\foo\bar\project_name"},
          "textures": { "darwin": "/textures/project_name", 
                        "linux2": "/textures/project_name",
                        "win32" : "c:\textures\project_name"}}
        
        The operating systems are enumerated using sys.platform jargon.
        
        :param project_disk_name: string with a project name.
        :returns: Dictionary, see above.
        """
        return_data = {}
        for s in self._params.get_required_storages():
            return_data[s] = {}
            return_data[s]["darwin"] = self._params.preview_project_path(s, project_disk_name, "darwin")
            return_data[s]["win32"] = self._params.preview_project_path(s, project_disk_name, "win32")
            return_data[s]["linux2"] = self._params.preview_project_path(s, project_disk_name, "linux2") 
        
        return return_data
        
    def set_project_disk_name(self, project_disk_name, create_folders=True):
        """
        Set the desired name of the project.
        May raise exception if the name is not valid.
        
        :param project_disk_name: string with a project name
        :param create_folders: if set to true, the wizard will attempt to create project root folders
                               if these don't already exist. 
        """

        # by default, the wizard will also try to help out with the creation of
        # the project root folder if it doesn't already exist! 
        if create_folders:
            
            # make sure name is valid before starting to create directories...
            self._params.validate_project_disk_name(project_disk_name)
            self._log.debug("Will try to create project folders on disk...")
            for s in self._params.get_required_storages():
                
                # get the full path
                proj_path = self._params.preview_project_path(s, project_disk_name, sys.platform)
                
                if not os.path.exists(proj_path):
                    self._log.info("Creating project folder '%s'..." % proj_path)
                    old_umask = os.umask(0)
                    try:
                        os.makedirs(proj_path, 0777)
                    finally:
                        os.umask(old_umask)
                    self._log.debug("...done!")
                
                else:
                    self._log.debug("Storage '%s' - project folder '%s' - already exists!" % (s, proj_path))
        
        # lastly, register the name in shotgun
        self._params.set_project_disk_name(project_disk_name)
            
    def get_default_configuration_location(self):
        """
        Returns default suggested location for configurations.
        Returns a dictionary with sys.platform style keys linux2/win32/darwin, e.g.
        
        { "darwin": "/foo/bar/project_name", 
          "linux2": "/foo/bar/project_name",
          "win32" : "c:\foo\bar\project_name"}        

        :returns: dictionary with paths
        """

        # the logic here is as follows:
        # 1. if the config comes from an existing project, base the config location on this
        # 2. if not, find the most recent primary pipeline config and base location on this
        # 3. failing that (meaning no projects have been set up ever) return None

        # now check the shotgun data
        new_proj_disk_name = self._params.get_project_disk_name() # e.g. 'foo/bar_baz'
        new_proj_disk_name_win = new_proj_disk_name.replace("/", "\\")  # e.g. 'foo\bar_baz'
         
        data = self._params.get_configuration_shotgun_info()
        
        if not data:
            # we are not based on an existing project. Instead pick the last primary config
            data = self._sg.find_one("PipelineConfiguration", 
                                     [["code", "is", "primary"]],
                                     ["id", 
                                      "mac_path", 
                                      "windows_path", 
                                      "linux_path", 
                                      "project", 
                                      "project.Project.tank_name"],
                                     [{"field_name": "created_at", "direction": "desc"}])

        if not data:
            # there are no primary configurations registered. This means that we are setting up
            # our very first project and cannot really suggest any config locations
            self._log.debug("No configs available to generate preview config values. Returning None.")            
            suggested_defaults = {"darwin": None, "linux2": None, "win32": None}
            
        else:
            # now take the pipeline config paths, and try to replace the current project name
            # in these paths by the new project name
            self._log.debug("Basing config values on the following shotgun pipeline config: %s" % data)
            
            # get the project path for this project
            old_project_disk_name = data["project.Project.tank_name"]  # e.g. 'foo/bar_baz'
            old_project_disk_name_win = old_project_disk_name.replace("/", "\\")  # e.g. 'foo\bar_baz'
            
            # now replace the project path in the pipeline configuration 
            suggested_defaults = {"darwin": None, "linux2": None, "win32": None}
            
            # go through each pipeline config path, try to find the project disk name as part of this
            # path. if that exists, replace with the new project disk name
            # here's the logic:
            #
            # project name:     'my_proj'
            # new project name: 'new_proj'
            #
            # pipeline config: /mnt/configs/my_proj/configz -> /mnt/configs/new_proj/configz
            #
            # if the project name isn't found as part of the config path, none is returned
            #
            # pipeline config: /mnt/configs/myproj/configz -> None
            #
            if data["mac_path"] and old_project_disk_name in data["mac_path"]:
                suggested_defaults["darwin"] = data["mac_path"].replace(old_project_disk_name, new_proj_disk_name)

            if data["linux_path"] and old_project_disk_name in data["linux_path"]:
                suggested_defaults["linux2"] = data["linux_path"].replace(old_project_disk_name, new_proj_disk_name)

            if data["windows_path"] and old_project_disk_name_win in data["windows_path"]:
                suggested_defaults["win32"] = data["windows_path"].replace(old_project_disk_name_win, new_proj_disk_name_win)
                
        return suggested_defaults
    
    def validate_configuration_location(self, linux_path, windows_path, macosx_path):
        """
        Validates a potential location for the pipeline configuration. 
        Raises exceptions in case the validation fails.
        
        :param linux_path: Path on linux
        :param windows_path: Path on windows
        :param macosx_path: Path on mac
        """
        self._params.validate_configuration_location(linux_path, windows_path, macosx_path)
            
    def set_configuration_location(self, linux_path, windows_path, macosx_path):
        """
        Specifies where the pipeline configuration should be located.
        
        :param linux_path: Path on linux 
        :param windows_path: Path on windows
        :param macosx_path: Path on mac
        """
        self._params.set_configuration_location(linux_path, windows_path, macosx_path)
    
    def execute(self):
        """
        Execute the actual setup process.
        """
        
        self._log.debug("Start preparing for project setup!")
        
        # first, work out which version of the core we should be associate the new project with.
        # this logic follows a similar pattern to the default config generation.
        #
        # A. If the config template is a project in shotgun, use its core.
        #    If this core is localized, then localize this project too
        
        # B. Otherwise, try to find the most recent primary pipeline config in shotgun and use its core
        #    If this core is localized, then localize this project too
        #
        # C. If there are no recent pipeline configs or if the config isn't valid, fall back on the 
        #    currently executing core API. Always localize in this case.
        
        
        # the defaults is to localize and pick up current
        localize_api = True
        curr_core_path = pipelineconfig_utils.get_path_to_current_core()
        core_path_dict = pipelineconfig_utils.resolve_all_os_paths_to_core(curr_core_path)
        
        # first try to get shotgun pipeline config data from the config template
        data = self._params.get_configuration_shotgun_info()
        
        if data:
            self._log.debug("Will try to inherit core from the config template: %s" % data)
        
        else:
            # the config template isn't a shotgun pipeline config. So fall back
            # on using the most recent primary one
            data = self._sg.find_one("PipelineConfiguration", 
                                     [["code", "is", "primary"]],
                                     ["id", 
                                      "mac_path", 
                                      "windows_path", 
                                      "linux_path", 
                                      "project", 
                                      "project.Project.tank_name"],
                                     [{"field_name": "created_at", "direction": "desc"}])

            if not data:
                self._log.debug("No existing projects in shotgun. Will try to inherit the core from the running code.")
            else:
                self._log.debug("Will try to inherit the core from the most recent project: %s" % data)
        
        # proceed to try to find the core API  
        if data:
            lookup = {"darwin": "mac_path", "linux2": "linux_path", "win32": "windows_path"}
            pipeline_config_root_path = data[ lookup[sys.platform] ]
            
            if pipeline_config_root_path and os.path.exists(pipeline_config_root_path):
                # looks like this exists - try to resolve its core API location
                core_api_root = pipelineconfig_utils.get_core_path_for_config(pipeline_config_root_path)
                
                if core_api_root:
                    # core api resolved correctly!
                    # now get all three platforms
                    core_path_dict = pipelineconfig_utils.resolve_all_os_paths_to_core(core_api_root)
                    self._log.debug("Will use pipeline configuration here: %s" % pipeline_config_root_path)
                    self._log.debug("This has an associated core here: %s" % core_api_root)

                    # now check the logic for localization:
                    # if this core that we have found and resolved is localized,
                    # we localize the new project as well.
                    if pipelineconfig_utils.is_localized(pipeline_config_root_path):
                        localize_api = True
                    else:
                        localize_api = False
        
        # ok - we are good to go! Set the core to use
        self._params.set_associated_core_path(core_path_dict["linux2"], 
                                              core_path_dict["win32"], 
                                              core_path_dict["darwin"])
        
        # run overall validation of the project setup
        self._params.pre_setup_validation()
        
        # and finally carry out the setup
        run_project_setup(self._log, self._sg, self._sg_app_store, self._sg_app_store_script_user, self._params)
        
        # check if we should run the localization afterwards
        if localize_api:
            core.do_localize(self._log, 
                             self._params.get_configuration_location(sys.platform), 
                             suppress_prompts=True)
        
