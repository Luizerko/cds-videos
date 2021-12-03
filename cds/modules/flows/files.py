# -*- coding: utf-8 -*-
#
# This file is part of Invenio.
# Copyright (C) 2021 CERN.
#
# Invenio is free software; you can redistribute it
# and/or modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# Invenio is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Invenio; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place, Suite 330, Boston,
# MA 02111-1307, USA.
#
# In applying this license, CERN does not
# waive the privileges and immunities granted to it by virtue of its status
# as an Intergovernmental Organization or submit itself to any jurisdiction.

from __future__ import absolute_import

import os
import shutil
import tempfile
from contextlib import contextmanager

from invenio_db import db
from invenio_files_rest.models import (
    ObjectVersion,
    ObjectVersionTag,
    as_object_version,
)

from ..xrootd.utils import file_opener_xrootd


def _rename_key(object_version):
    """Renames the object_version key to avoid issues with subformats
    objectVersions key.
    """
    prefix = "uploaded_"
    if not object_version.key.startswith(prefix):
        object_version.key = prefix + object_version.key


def init_object_version(flow):
    """Create, if doesn't exists, the version object for the flow."""
    flow_id = str(flow.id)
    has_user_uploaded_file = flow.payload.get("version_id")
    bucket_id = flow.payload["bucket_id"]

    with db.session.begin_nested():
        # create a object version if doesn't exists
        if has_user_uploaded_file:
            version_id = flow.payload["version_id"]
            object_version = as_object_version(version_id)
        else:
            object_version = ObjectVersion.create(
                bucket=bucket_id, key=flow.payload["key"]
            )
            ObjectVersionTag.create(
                object_version, "uri_origin", flow.payload["uri"]
            )

        # add tag with corresponding event
        ObjectVersionTag.create_or_update(object_version, "flow_id", flow_id)
        # add tag for preview
        ObjectVersionTag.create_or_update(object_version, "preview", "true")
        # add tags for file type
        ObjectVersionTag.create_or_update(
            object_version, "media_type", "video"
        )
        ObjectVersionTag.create_or_update(
            object_version, "context_type", "master"
        )
        _rename_key(object_version)
    return object_version


def dispose_object_version(object_version):
    """Clean up resources related to an ObjectVersion."""
    object_version = as_object_version(object_version)
    # remove the object version
    object_version.bucket.locked = False
    ObjectVersion.delete(bucket=object_version.bucket, key=object_version.key)


@contextmanager
def move_file_into_local(obj, delete=True):
    """Move file from XRootD accessed file system into a local path

    :param obj: Object version to make locally available.
    :param delete: Whether or not the tmp file should be deleted on exit.
    """
    if os.path.exists(obj.file.uri):
        yield obj.file.uri
    else:
        temp_location = obj.get_tags().get("temp_location", None)
        if not temp_location:
            temp_folder = tempfile.mkdtemp()
            temp_location = os.path.join(temp_folder, "data")

            with open(temp_location, "wb") as dst:
                shutil.copyfileobj(file_opener_xrootd(obj.file.uri, "rb"), dst)

            ObjectVersionTag.create(obj, "temp_location", temp_location)
            db.session.commit()
        else:
            temp_folder = os.path.dirname(temp_location)
        try:
            yield temp_location
        except:
            shutil.rmtree(temp_folder)
            ObjectVersionTag.delete(obj, "temp_location")
            db.session.commit()
            raise
        else:
            if delete:
                shutil.rmtree(temp_folder)
                ObjectVersionTag.delete(obj, "temp_location")
                db.session.commit()
