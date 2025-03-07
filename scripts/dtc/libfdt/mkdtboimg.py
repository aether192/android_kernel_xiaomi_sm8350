#! /usr/bin/env python
# Copyright 2017, The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function

"""Tool for packing multiple DTB/DTBO files into a single image"""

import argparse
import os
from array import array
from collections import namedtuple
import struct
from sys import stdout
import zlib

class CompressionFormat(object):
    """Enum representing DT compression format for a DT entry.
    """
    NO_COMPRESSION = 0x00
    ZLIB_COMPRESSION = 0x01
    GZIP_COMPRESSION = 0x02

class DtEntry(object):
    """Provides individual DT image file arguments to be added to a DTBO.

    Attributes:
        _REQUIRED_KEYS: 'keys' needed to be present in the dictionary passed to instantiate
            an object of this class.
        _COMPRESSION_FORMAT_MASK: Mask to retrieve compression info for DT entry from flags field
            when a DTBO header of version 1 is used.
    """
    _COMPRESSION_FORMAT_MASK = 0x0f
    REQUIRED_KEYS = ('dt_file', 'dt_size', 'dt_offset', 'id', 'rev', 'flags',
                     'custom0', 'custom1', 'custom2')

    @staticmethod
    def __get_number_or_prop(arg):
        """Converts string to integer or reads the property from DT image.

        Args:
            arg: String containing the argument provided on the command line.

        Returns:
            An integer property read from DT file or argument string
            converted to integer
        """

        if not arg or arg[0] == '+' or arg[0] == '-':
            raise ValueError('Invalid argument passed to DTImage')
        if arg[0] == '/':
            # TODO(b/XXX): Use pylibfdt to get property value from DT
            raise ValueError('Invalid argument passed to DTImage')
        else:
            base = 10
            if arg.startswith('0x') or arg.startswith('0X'):
                base = 16
            elif arg.startswith('0'):
                base = 8
            return int(arg, base)

    def __init__(self, **kwargs):
        """Constructor for DtEntry object.

        Initializes attributes from dictionary object that contains
        values keyed with names equivalent to the class's attributes.

        Args:
            kwargs: Dictionary object containing values to instantiate
                class members with. Expected keys in dictionary are from
                the tuple (_REQUIRED_KEYS)
        """

        missing_keys = set(self.REQUIRED_KEYS) - set(kwargs)
        if missing_keys:
            raise ValueError('Missing keys in DtEntry constructor: %r' %
                             sorted(missing_keys))

        self.__dt_file = kwargs['dt_file']
        self.__dt_offset = kwargs['dt_offset']
        self.__dt_size = kwargs['dt_size']
        self.__id = self.__get_number_or_prop(kwargs['id'])
        self.__rev = self.__get_number_or_prop(kwargs['rev'])
        self.__flags = self.__get_number_or_prop(kwargs['flags'])
        self.__custom0 = self.__get_number_or_prop(kwargs['custom0'])
        self.__custom1 = self.__get_number_or_prop(kwargs['custom1'])
        self.__custom2 = self.__get_number_or_prop(kwargs['custom2'])

    def __str__(self):
        sb = []
        sb.append('{key:>20} = {value:d}'.format(key='dt_size',
                                                 value=self.__dt_size))
        sb.append('{key:>20} = {value:d}'.format(key='dt_offset',
                                                 value=self.__dt_offset))
        sb.append('{key:>20} = {value:08x}'.format(key='id',
                                                   value=self.__id))
        sb.append('{key:>20} = {value:08x}'.format(key='rev',
                                                   value=self.__rev))
        sb.append('{key:>20} = {value:08x}'.format(key='custom[0]',
                                                   value=self.__flags))
        sb.append('{key:>20} = {value:08x}'.format(key='custom[1]',
                                                   value=self.__custom0))
        sb.append('{key:>20} = {value:08x}'.format(key='custom[2]',
                                                   value=self.__custom1))
        sb.append('{key:>20} = {value:08x}'.format(key='custom[3]',
                                                   value=self.__custom2))
        return '\n'.join(sb)

    def compression_info(self, version):
        """CompressionFormat: compression format for DT image file.

           Args:
                version: Version of DTBO header, compression is only
                         supported from version 1.
        """
        if version is 0:
            return CompressionFormat.NO_COMPRESSION
        return self.flags & self._COMPRESSION_FORMAT_MASK

    @property
    def dt_file(self):
        """file: File handle to the DT image file."""
        return self.__dt_file

    @property
    def size(self):
        """int: size in bytes of the DT image file."""
        return self.__dt_size

    @size.setter
    def size(self, value):
        self.__dt_size = value

    @property
    def dt_offset(self):
        """int: offset in DTBO file for this DT image."""
        return self.__dt_offset

    @dt_offset.setter
    def dt_offset(self, value):
        self.__dt_offset = value

    @property
    def image_id(self):
        """int: DT entry _id for this DT image."""
        return self.__id

    @property
    def rev(self):
        """int: DT entry _rev for this DT image."""
        return self.__rev

    @property
    def flags(self):
        """int: DT entry _flags for this DT image."""
        return self.__flags

    @property
    def custom0(self):
        """int: DT entry _custom0 for this DT image."""
        return self.__custom0

    @property
    def custom1(self):
        """int: DT entry _custom1 for this DT image."""
        return self.__custom1

    @property
    def custom2(self):
        """int: DT entry custom2 for this DT image."""
        return self.__custom2


class Dtbo(object):
    """
    Provides parser, reader, writer for dumping and creating Device Tree Blob
    Overlay (DTBO) images.

    Attributes:
        _DTBO_MAGIC: Device tree table header magic.
        _ACPIO_MAGIC: Advanced Configuration and Power Interface table header
                      magic.
        _DT_TABLE_HEADER_SIZE: Size of Device tree table header.
        _DT_TABLE_HEADER_INTS: Number of integers in DT table header.
        _DT_ENTRY_HEADER_SIZE: Size of Device tree entry header within a DTBO.
        _DT_ENTRY_HEADER_INTS: Number of integers in DT entry header.
        _GZIP_COMPRESSION_WBITS: Argument 'wbits' for gzip compression
        _ZLIB_DECOMPRESSION_WBITS: Argument 'wbits' for zlib/gzip compression
    """

    _DTBO_MAGIC = 0xd7b7ab1e
    _ACPIO_MAGIC = 0x41435049
    _DT_TABLE_HEADER_SIZE = struct.calcsize('>8I')
    _DT_TABLE_HEADER_INTS = 8
    _DT_ENTRY_HEADER_SIZE = struct.calcsize('>8I')
    _DT_ENTRY_HEADER_INTS = 8
    _GZIP_COMPRESSION_WBITS = 31
    _ZLIB_DECOMPRESSION_WBITS = 47

    def _update_dt_table_header(self):
        """Converts header entries into binary data for DTBO header.

        Packs the current Device tree table header attribute values in
        metadata buffer.
        """
        struct.pack_into('>8I', self.__metadata, 0, self.magic,
                         self.total_size, self.header_size,
                         self.dt_entry_size, self.dt_entry_count,
                         self.dt_entries_offset, self.page_size,
                         self.version)

    def _update_dt_entry_header(self, dt_entry, metadata_offset):
        """Converts each DT entry header entry into binary data for DTBO file.

        Packs the current device tree table entry attribute into
        metadata buffer as device tree entry header.

        Args:
            dt_entry: DtEntry object for the header to be packed.
            metadata_offset: Offset into metadata buffer to begin writing.
            dtbo_offset: Offset where the DT image file for this dt_entry can
                be found in the resulting DTBO image.
        """
        struct.pack_into('>8I', self.__metadata, metadata_offset, dt_entry.size,
                         dt_entry.dt_offset, dt_entry.image_id, dt_entry.rev,
                         dt_entry.flags, dt_entry.custom0, dt_entry.custom1,
                         dt_entry.custom2)

    def _update_metadata(self):
        """Updates the DTBO metadata.

        Initialize the internal metadata buffer and fill it with all Device
        Tree table entries and update the DTBO header.
        """

        self.__metadata = array('c', ' ' * self.__metadata_size)
        metadata_offset = self.header_size
        for dt_entry in self.__dt_entries:
            self._update_dt_entry_header(dt_entry, metadata_offset)
            metadata_offset += self.dt_entry_size
        self._update_dt_table_header()

    def _read_dtbo_header(self, buf):
        """Reads DTBO file header into metadata buffer.

        Unpack and read the DTBO table header from given buffer. The
        buffer size must exactly be equal to _DT_TABLE_HEADER_SIZE.

        Args:
            buf: Bytebuffer read directly from the file of size
                _DT_TABLE_HEADER_SIZE.
        """
        (self.magic, self.total_size, self.header_size,
         self.dt_entry_size, self.dt_entry_count, self.dt_entries_offset,
         self.page_size, self.version) = struct.unpack_from('>8I', buf, 0)

        # verify the header
        if self.magic != self._DTBO_MAGIC and self.magic != self._ACPIO_MAGIC:
            raise ValueError('Invalid magic number 0x%x in DTBO/ACPIO file' %
                             (self.magic))

        if self.header_size != self._DT_TABLE_HEADER_SIZE:
            raise ValueError('Invalid header size (%d) in DTBO/ACPIO file' %
                             (self.header_size))

        if self.dt_entry_size != self._DT_ENTRY_HEADER_SIZE:
            raise ValueError('Invalid DT entry header size (%d) in DTBO/ACPIO file' %
                             (self.dt_entry_size))

    def _read_dt_entries_from_metadata(self):
        """Reads individual DT entry headers from metadata buffer.

        Unpack and read the DTBO DT entry headers from the internal buffer.
        The buffer size must exactly be equal to _DT_TABLE_HEADER_SIZE +
        (_DT_ENTRY_HEADER_SIZE * dt_entry_count). The method raises exception
        if DT entries have already been set for this object.
        """

        if self.__dt_entries:
            raise ValueError('DTBO DT entries can be added only once')

        offset = self.dt_entries_offset / 4
        params = {}
        params['dt_file'] = None
        for i in range(0, self.dt_entry_count):
            dt_table_entry = self.__metadata[offset:offset + self._DT_ENTRY_HEADER_INTS]
            params['dt_size'] = dt_table_entry[0]
            params['dt_offset'] = dt_table_entry[1]
            for j in range(2, self._DT_ENTRY_HEADER_INTS):
                params[DtEntry.REQUIRED_KEYS[j + 1]] = str(dt_table_entry[j])
            dt_entry = DtEntry(**params)
            self.__dt_entries.append(dt_entry)
            offset += self._DT_ENTRY_HEADER_INTS

    def _read_dtbo_image(self):
        """Parse the input file and instantiate this object."""

        # First check if we have enough to read the header
        file_size = os.fstat(self.__file.fileno()).st_size
        if file_size < self._DT_TABLE_HEADER_SIZE:
            raise ValueError('Invalid DTBO file')

        self.__file.seek(0)
        buf = self.__file.read(self._DT_TABLE_HEADER_SIZE)
        self._read_dtbo_header(buf)

        self.__metadata_size = (self.header_size +
                                self.dt_entry_count * self.dt_entry_size)
        if file_size < self.__metadata_size:
            raise ValueError('Invalid or truncated DTBO file of size %d expected %d' %
                             file_size, self.__metadata_size)

        num_ints = (self._DT_TABLE_HEADER_INTS +
                    self.dt_entry_count * self._DT_ENTRY_HEADER_INTS)
        if self.dt_entries_offset > self._DT_TABLE_HEADER_SIZE:
            num_ints += (self.dt_entries_offset - self._DT_TABLE_HEADER_SIZE) / 4
        format_str = '>' + str(num_ints) + 'I'
        self.__file.seek(0)
        self.__metadata = struct.unpack(format_str,
                                        self.__file.read(self.__metadata_size))
        self._read_dt_entries_from_metadata()

    def _find_dt_entry_with_same_file(self, dt_entry):
        """Finds DT Entry that has identical backing DT file.

        Args:
            dt_entry: DtEntry object whose 'dtfile' we find for existence in the
                current 'dt_entries'.
        Returns:
            If a match by file path is found, the corresponding DtEntry object
            from internal list is returned. If not, 'None' is returned.
        """

        dt_entry_path = os.path.realpath(dt_entry.dt_file.name)
        for entry in self.__dt_entries:
            entry_path = os.path.realpath(entry.dt_file.name)
            if entry_path == dt_entry_path:
                return entry
        return None

    def __init__(self, file_handle, dt_type='dtb', page_size=None, version=0):
        """Constructor for Dtbo Object

        Args:
            file_handle: The Dtbo File handle corresponding to this object.
                The file handle can be used to write to (in case of 'create')
                or read from (in case of 'dump')
        """

        self.__file = file_handle
        self.__dt_entries = []
        self.__metadata = None
        self.__metadata_size = 0

        # if page_size is given, assume the object is being instantiated to
        # create a DTBO file
        if page_size:
            if dt_type == 'acpi':
                self.magic = self._ACPIO_MAGIC
            else:
                self.magic = self._DTBO_MAGIC
            self.total_size = self._DT_TABLE_HEADER_SIZE
            self.header_size = self._DT_TABLE_HEADER_SIZE
            self.dt_entry_size = self._DT_ENTRY_HEADER_SIZE
            self.dt_entry_count = 0
            self.dt_entries_offset = self._DT_TABLE_HEADER_SIZE
            self.page_size = page_size
            self.version = version
            self.__metadata_size = self._DT_TABLE_HEADER_SIZE
        else:
            self._read_dtbo_image()

    def __str__(self):
        sb = []
        sb.append('dt_table_header:')
        _keys = ('magic', 'total_size', 'header_size', 'dt_entry_size',
                 'dt_entry_count', 'dt_entries_offset', 'page_size', 'version')
        for key in _keys:
            if key == 'magic':
                sb.append('{key:>20} = {value:08x}'.format(key=key,
                                                           value=self.__dict__[key]))
            else:
                sb.append('{key:>20} = {value:d}'.format(key=key,
                                                         value=self.__dict__[key]))
        count = 0
        for dt_entry in self.__dt_entries:
            sb.append('dt_table_entry[{0:d}]:'.format(count))
            sb.append(str(dt_entry))
            count = count + 1
        return '\n'.join(sb)

    @property
    def dt_entries(self):
        """Returns a list of DtEntry objects found in DTBO file."""
        return self.__dt_entries

    def compress_dt_entry(self, compression_format, dt_entry_file):
        """Compresses a DT entry.

        Args:
            compression_format: Compression format for DT Entry
            dt_entry_file: File handle to read DT entry from.

        Returns:
            Compressed DT entry and its length.

        Raises:
            ValueError if unrecognized compression format is found.
        """
        compress_zlib = zlib.compressobj()  #  zlib
        compress_gzip = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION,
                                         zlib.DEFLATED, self._GZIP_COMPRESSION_WBITS)  #  gzip
        compression_obj_dict = {
            CompressionFormat.NO_COMPRESSION: None,
            CompressionFormat.ZLIB_COMPRESSION: compress_zlib,
            CompressionFormat.GZIP_COMPRESSION: compress_gzip,
        }

        if compression_format not in compression_obj_dict:
            ValueError("Bad compression format %d" % compression_format)

        if compression_format is CompressionFormat.NO_COMPRESSION:
            dt_entry = dt_entry_file.read()
        else:
            compression_object = compression_obj_dict[compression_format]
            dt_entry_file.seek(0)
            dt_entry = compression_object.compress(dt_entry_file.read())
            dt_entry += compression_object.flush()
        return dt_entry, len(dt_entry)

    def add_dt_entries(self, dt_entries):
        """Adds DT image files to the DTBO object.

        Adds a list of Dtentry Objects to the DTBO image. The changes are not
        committed to the output file until commit() is called.

        Args:
            dt_entries: List of DtEntry object to be added.

        Returns:
            A buffer containing all DT entries.

        Raises:
            ValueError: if the list of DT entries is empty or if a list of DT entries
                has already been added to the DTBO.
        """
        if not dt_entries:
            raise ValueError('Attempted to add empty list of DT entries')

        if self.__dt_entries:
            raise ValueError('DTBO DT entries can be added only once')

        dt_entry_count = len(dt_entries)
        dt_offset = (self.header_size +
                     dt_entry_count * self.dt_entry_size)

        dt_entry_buf = ""
        for dt_entry in dt_entries:
            if not isinstance(dt_entry, DtEntry):
                raise ValueError('Adding invalid DT entry object to DTBO')
            entry = self._find_dt_entry_with_same_file(dt_entry)
            dt_entry_compression_info = dt_entry.compression_info(self.version)
            if entry and (entry.compression_info(self.version)
                          == dt_entry_compression_info):
                dt_entry.dt_offset = entry.dt_offset
                dt_entry.size = entry.size
            else:
                dt_entry.dt_offset = dt_offset
                compressed_entry, dt_entry.size = self.compress_dt_entry(dt_entry_compression_info,
                                                                         dt_entry.dt_file)
                dt_entry_buf += compressed_entry
                dt_offset += dt_entry.size
                self.total_size += dt_entry.size
            self.__dt_entries.append(dt_entry)
            self.dt_entry_count += 1
            self.__metadata_size += self.dt_entry_size
            self.total_size += self.dt_entry_size

        return dt_entry_buf

    def extract_dt_file(self, idx, fout, decompress):
        """Extract DT Image files embedded in the DTBO file.

        Extracts Device Tree blob image file at given index into a file handle.

        Args:
            idx: Index of the DT entry in the DTBO file.
            fout: File handle where the DTB at index idx to be extracted into.
            decompress: If a DT entry is compressed, decompress it before writing
                it to the file handle.

        Raises:
            ValueError: if invalid DT entry index or compression format is detected.
        """
        if idx > self.dt_entry_count:
            raise ValueError('Invalid index %d of DtEntry' % idx)

        size = self.dt_entr
