============================
JupyterHub Traffic Simulator
============================

The JupyterHub Traffic Simulator (``hubtraf``) is a Python library,
application & helm-chart that can simulate users on a JupyterHub. Integration
testing & performance testing are the primary use cases. It replaces
the ``jupyter-loadtest`` project.

What does ``hubtraf`` do?
-------------------------

* Simulates a set of users accessing the specified Hub instance
* User logins are uniformly distributed over a start delay period
* Session durations are uniformly distributed over the configured run time
* Sessions consist of logging in, starting a server, starting a kernel, execute
  calculations, and stopping the server
* Logs are output and optionally collected via ``fluentd`` (helm-chart only)

Prerequisites
-------------

Hubtraf assumes a JupyterHub instance running with:

* Dummy authentication (LTI in progress)
* Classic notebook (i.e., not Lab)


Helm Usage
----------

These instructions assume that you have JupyterHub installed using Helm
via `Zero to JupyterHub <https://zero-to-jupyterhub.readthedocs.io/>`_.

1. Clone this repository

   .. code-block:: bash

      git clone  https://github.com/yuvipanda/hubtraf.git


2. Configure the Helm Chart

   .. code-block:: bash

      helm install --namespace=hubtraf --name=hubtraf hubtraf/helm-chart \
         --set hub.url=<url to your hub instance>

   Additional configuration options include:

   ===================   =======================================================
   **Option**            **Description**
   -------------------   -------------------------------------------------------
   hub.url               Hub URL to send traffic to (without a trailing /)
   hub.ip                IP address of Hub instance (may be used instead of URL)
   users.count           Number of users to simulate
   users.startTime.max   Max seconds by which all users are logged in, default 60
   users.runTime.min     Min seconds user is active for, default 60
   users.runTime.max     Max seconds user is active for, defautl 300
   rbac.enabled          Whether RBAC is enabled, default true
   image.repository      Repository for hubtraf image
   image.tag             Hubtraf image tag, default ``v2``
   image.pullPolicy      Image pull policy, default ``Always``
   ===================   =======================================================

The Helm chart installs `fluent-bit <https://fluentbit.io/>`_ to capture logs
from ``hubtraf`` jobs.


Python Usage
------------
``hubtraf`` can also be executed as a Python application:

1. Clone this repository

   .. code-block:: bash

      git clone  https://github.com/yuvipanda/hubtraf.git


2. Install and run

   .. code-block:: bash

      cd hubtraf
      pip install .
      hubtraf-simulate hub_url user_count


  Additional options included:

  =================================  =======================================================
  **Arguments/Flags**                **Description**
  ---------------------------------  -------------------------------------------------------
  hub_url                            Hub URL to send traffic to (without a trailing /)
  user_count                         Number of users to simulate
  ``--user-prefix``                  Prefix to use when generating user names, default = hostname
  ``--user-session-min-runtime``     Min seconds user is active for, default 60
  ``--user-session-max-runtime``     Max seconds user is active for, defautl 300
  ``--user-ession-max-start-delay``  Max seconds by which all users are have logged in, default 60
  ``--json``                         True if output should be JSON formatted
  =================================  =======================================================

