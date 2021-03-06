# Copyright 2018 Google Inc. All Rights Reserved.
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

import re

import os

import github3

try:
    from common import GuestStepProperties, ConfigUtils, GitUtils, BaseGuest
except ImportError:
    from artmanflow.steps.common import \
        GuestStepProperties, ConfigUtils, GitUtils, BaseGuest


class JavaSourcesStagingGuest(BaseGuest):
    def execute(self):
        try:
            self.before_execute()
            staging_name = self.checkout_git_output_repo(
                self._config['staging'])
            client_folders = self._extract_client_folders()
            self._copy_artifacts_to_staging(staging_name, client_folders)
            self._build_and_test(staging_name)
            self._git_commit_and_push(staging_name)
            pr_url = self._post_pr()
            self._dump_output({'pr_url': pr_url})
            self.after_execute(self._config['debug_mode'])
        except Exception as e:
            self.after_execute(True, e)
            raise

    def _extract_client_folders(self):
        exp = re.compile(r'^\./([^/]+/){2}$')
        art_name = self._config['generator_artifacts']['sources_zip']

        art_list = self.check_command(['tar', '-tf', art_name],
                                      self._guest.guest_root_path())
        art_list = art_list.decode('UTF-8').split('\n')
        client_folders = []
        for art in art_list:
            if exp.match(art):
                client_folders.append(art)

        return client_folders

    def _copy_artifacts_to_staging(self, staging_name, client_folders):
        staging_path = self._guest.guest_root_subpath(staging_name)
        dests = []
        for client_folder in client_folders:
            dest = self._guest.relative_path(['generated', client_folder])
            dest_path = self._guest.guest_root_subpath([staging_name, dest])
            self.check_command(
                ['git', 'rm', '-r', '--force', '--ignore-unmatch', dest],
                staging_path)
            if not os.path.exists(dest_path):
                os.makedirs(dest_path)
            dests.append(dest)

        unzip_dest = self._guest.guest_root_subpath([staging_name, 'generated'])
        self.run_command(
            ['tar', '-pxzf', self._config['generator_artifacts']['sources_zip'],
             '-C', unzip_dest, '--wildcards', './java/*'],
            self._guest.guest_root_path())
        for dest in dests:
            self.run_command(['git', 'add', dest], staging_path)

    def _git_commit_and_push(self, staging_name):
        staging_path = self._guest.guest_root_subpath(staging_name)
        self.run_command(['git', 'status'],
                         self._guest.guest_root_subpath(staging_name))
        self.run_command(['git', 'commit', '--allow-empty', '-m',
                          'Regenerate Java client sources'],
                         staging_path)
        self.run_command(['git', 'push', '-u', 'origin',
                          self._config['staging']['git_branch']],
                         staging_path)

    def _build_and_test(self, staging_name):
        if not self._config['staging']['run_tests']:
            return
        cwd = self._guest.guest_root_subpath(
            [staging_name, 'generated', 'java'])
        self.run_command(['./gradlew', 'clean', 'test'], cwd)

    def _post_pr(self):
        config = self._config['staging']
        repo_name = config['git_repo']
        repo_owner, repo_name = GitUtils.repo_properties(repo_name)

        gh = github3.login(config['git_user_name'],
                           config['git_security_token'])
        repo = gh.repository(repo_owner, repo_name)

        pr_base = 'master'
        # pr_head = "%s:%s" % (config['git_user_name'], config['git_branch'])
        pr_head = config['git_branch']

        self.puts(
            'Creating pull request, base: %s, head: %s' % (pr_base, pr_head))
        pr = repo.create_pull(
            base=pr_base,
            body='This PR is automatically generated by Artmanflow tool',
            head=pr_head,
            title='Artman Workflow Java sources staging'
        )

        if not pr:
            raise RuntimeError('Pull request creation failed.')

        self.puts('Pull request created successfully: %s' % pr.html_url)

        return pr.html_url

    def _dump_output(self, output_yaml):
        output_yaml_path = self._guest.guest_output_dir_subpath(
            ConfigUtils.artifact_yaml_name())
        ConfigUtils.dump_config(output_yaml, output_yaml_path)
        self.change_file_permissions(output_yaml_path)


if __name__ == '__main__':
    execution_config = ConfigUtils.read_config()
    step = JavaSourcesStagingGuest(execution_config)
    step.execute()
