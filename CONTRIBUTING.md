# Contributing

Blendkit add-on is an open-source project and we welcome contributions from the community.

1. Clone the repo: `git clone https://github.com/blenderkit/blenderkit --recursive` (recursive is needed as repository uses submodules [bk_client](https://github.com/BlenderKit/bk_client) and [bk_proxor](https://github.com/BlenderKit/bk_proxor)).
2. Enable the repository git hooks: `git config core.hooksPath .githooks` (this activates the `post-checkout` hook that keeps submodules in sync when you switch branches).
3. Make sure Python is available: `python --version`, if not install Python.
4. Make sure Go is available: `go version`, if not install Go.
5. Build the add-on: `python dev.py build`, the .zip file is located in `./out` directory.

## Building the add-on

Use `dev.py` script to build the add-on.
This script will copy relevant files to `out/blenderkit` directory (ignoring all files which are not needed in the add-on).
From this source the script will then create a zip file at `out/blenderkit.zip`.
This zip then can be used as a release of Blendkit.

To build run:
```
python dev.py build
```

### Development build

Script `dev.py` provides handy option `--install-at` to copy the `out/blenderkit` directly to Blender so you can quickly test the build just by starting the Blender without any further steps or symbolic links.
Just specify path to addons directory in `--install-at` flag.
Script will then remove old `Blendkit` directory in addons location and replace it with current build.

To build and copy to Blender 4.2.x addons directory and also clean blenderkit_data, run:

```
python dev.py build --install-at /path/to/blender/4.2/scripts/addons --clean-dir /Users/username/blenderkit_data/client/bin
```

To build and copy to Blender 4.2.x as extension, run:

```
python dev.py build --install-at /path/to/blender/4.2/extensions/user_default --clean-dir /Users/username/blenderkit_data/client/bin
```

NOTE: --clean-dir is required if you change anything in the bk_client, otherwise add-on will not copy the new binaries over the old ones.
We recommend using this command to clean all client binaries, while enabling you to continuously tail -f default.log file:

```
python dev.py build --install-at /path/to/blender/4.0/scripts/addons --clean-dir /Users/username/blenderkit_data/client/bin
```

## Add-on Architecture
Blendkit add-on is made of two main parts:
- Blender add-on written in Python, which is responsible for the user interface and interaction with Blender. It draws the search panel, does the snaping, asset imports, and communicates with the Client locally.
- [bk_client](https://github.com/BlenderKit/bk_client) written in Go, which serves as background HTTP server - a bridge between Blendkit add-on and Blendkit server. It's purpose is to offload the work from Blender and to provide a performant way to communicate with Blendkit server.

bk_client is compiled and it's binaries are bundled into the add-on .zip file, so the user does not need to install anything else than the add-on itself.
bk_client is included as a git submodule, its codebase and building scripts are part of the separate repository https://github.com/BlenderKit/bk_client.

Another submodule is [bk_proxor](https://github.com/BlenderKit/bk_proxor), which is responsible for the 3D visualisation of models during drag and drop.

### How it is packaged
Blendkit add-on is packaged as a zip file (standard way for Blender add-ons), which contains all the necessary files for the add-on to work.
This includes not only the Python files, icons and other files, but also the [bk_client](https://github.com/BlenderKit/bk_client) binaries for 3 platforms on 2 architectures (windows x86_64, windows arm64, macos x86_64, macos arm64, linux x86_64, linux arm64).
When add-on is registered, it chooses the correct Client binary for the platform and architecture and copies it to the user's Blendkit data directory, from this location the Client is later started.

### How it works
Communication between Add-on and Client happens in one way direction: add-on schedules Tasks via request and periodically gets updates about the progress and results of the tasks in reponses to the requests:
`Add-on -> Client -> Server`

1. add-on checks whether the Client is running. If it is not, it starts the Client binary located at `<global-directory>/client/bin/vX.Y.Z/bk_client-<platform>-<architecture>`,
2. add-on periodically asks for results with GET request and Client responds to the request,
3. if needed add-on sends requests (identifying itself with app_id which is PID of running Blender instance) for search, download asset, get notifications, download thumbnails etc. to the Client,
4. Client receives the request for work, saves it into `var Tasks map[int]map[string]*Task` and ASAP responds by OK to not block the add-on,
5. Client starts the work in goroutine, or makes request to Blendkit server, or combination of both,
6. When work is done, or response comes from Blendkit server, Client updates the results into `var Tasks map[int]map[string]*Task`.
7. next time when add-on periodically asks for results of the Tasks, Client sends the results as response.

Communication between Client and Server currently happens also in one way Client -> Server (Client makes requests to Server).

## Development

### Logging

Do not use `print()` statements in the code, use logging instead.
In the beginning of the file, there is a logger setup, if it is not already there, add it:
```python
import logging
bk_logger = logging.getLogger(__name__)
```

Then instead of `print()` use the `bk_logger`:
```python
bk_logger.debug("Some minor stuff happened")
bk_logger.info("Something expected has happened")
bk_logger.warning("Something unexpected has happened")
bk_logger.error("Something went very wrong")
```

If you have an exception which you can log, use `bk_logger.exception()`, e.g.:
```python
except Exception as e:
    bk_logger.exception("Something went wrong and you will see full traceback below")
```

### Codestyle

We use `isort` for imports sorting.
We use `black` for codestyle.
We try to type statically with `mypy.`.
We use `go fmt` for formatting Go code in `./client`.
We will use `ruff` for linting.

We define versions in `devs/requirements.txt` so the local development environment is consistent with CI/CD (Github Actions).
To install them in correct versions run: `pip3 install -U --user -r devs/requirements.txt`.

Before committing your changes, please run:
```
pdm run mypy .
pdm run isort .
pdm run black .
```

or if installed locally:
```
mypy .
isort .
black .
```

or just run `python3 dev.py format` to run all of them automatically.

Right now `isort` and `black` are required.
Pull requests will fail in CI/CD if they are not formatted properly and isort or black throws an error.

We are migrating towards `ruff` as well, but it is not required yet.
Please run `ruff` on files you have edited and try to fix all the errors.
Slowly we will add the ruff as a required check in CI/CD.


## Testing

Blendkit add-on uses tests implemented through `unittest` module.
As the add-on and its submodules require `bpy` module and interaction with Blender, the tests needs to be executed in the Python inside of the Blender.
This makes the tests to be on the edge between unit tests and integration tests.

The tests are defined in `tests/test_<name-of-tested-file>.py` files and their starting point is `tests/test.py` which is executed from `dev.py` script.

### Install dependencies

1. install `pdm` package manager (https://pdm-project.org/en/latest/#installation)
2. install developers dependencies `pdm install`
3. Verify installation:
```
pdm run black --version
pdm run isort --version
pdm run mypy --version
```

### Local testing

To test the add-on locally, make sure you have a Blender on your PATH.
Then run to test as legacy add-on:

```
python dev.py test --install-at /path/to/blender/4.2/scripts/addons
```

Or to test as extension:

```
python dev.py test --install-at /path/to/blender/4.2/extensions/user_default
```

NOTE: please make sure that version in the `--install-at` path must match the version of the Blender version you have on your PATH.
Otherwise the add-on with test files will be copied to Blender version 4.x, but tests will run on different Blender version 4.a with outdated (or missing) Blendkit build.

### Pull Requests

To contribute to the project, please create a Pull Request.
PR should contain a description of the changes and the reason for the changes.
Ideally PR should be linked to an issue in the issue tracker.

PR will be reviewed by the team and if it passes the automated tests and checks, it will be merged.

#### Automated tests

We run automated tests on: Pull Requests.
The tests and checks which must pass for PR to be accepted are:
- unit/integration tests on several versions of Blender 3.x.,
- `isort` check for validity of import sorting,
- `black` check for codestyle,
- `go fmt` check for formatting Go code in `./client`,
- automated build of the add-on.

Those CI/CD jobs are realized through Github workflows and are defined in `.github/workflows` directory.
For Pull Requests jobs it is in file: `.github/workflows/PR.yml`.
