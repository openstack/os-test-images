#!/usr/bin/python

import argparse
import logging
import os
import struct
import subprocess
import sys

import yaml

LOG = logging.getLogger('generate')


def footerify_vmdk(fn):
    """Convert a monolithicSparse to use a footer instead of just a header"""
    GD_AT_END = 0xffffffffffffffff

    with open(fn, 'rb+') as f:
        header = f.read(512)
        # Write the "expect a footer" sentinel into the header
        f.seek(56)
        f.write(struct.pack('<Q', GD_AT_END))
        # Add room for the footer marker, footer, and EOS marker, but
        # filled with zeroes (which is invalid)
        f.seek(0, 2)
        f.write(b'\x00' * 512 * 3)
        # This is the footer marker (type=3)
        f.seek(-512 * 3 + 12, 2)
        f.write(b'\x03\x00\x00\x00')
        # Second-to-last sector is the footer, which must be a copy of the
        # header but with gdOffset set to something other than the flag.
        f.seek(-512 * 2, 2)
        f.write(header)


POSTPROCS = {
    'footerify_vmdk': footerify_vmdk,
}


def generate_one(yamldef, output_dir):
    yamldef['filename'] = '%s.%s' % (yamldef['name'], yamldef['format'])
    vars = {
        'name': yamldef['name'],
        'filename': yamldef['filename'],
    }
    for i, one_cmd in enumerate(yamldef['generated_by']):
        if one_cmd:
            one_cmd %= vars
            LOG.info('Generating %s step %i/%i with %r',
                     yamldef['name'], i + 1, len(yamldef['generated_by']),
                     one_cmd)
            try:
                output = subprocess.check_output(one_cmd, shell=True,
                                                 cwd=output_dir,
                                                 stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                LOG.error('Command %r failed with %i: %s',
                          one_cmd, e.returncode, e.output)
                raise

            LOG.debug('Command %r returned %s', one_cmd, output)
        if 'postprocess' in yamldef:
            postproc = POSTPROCS[yamldef['postprocess']]
            LOG.info('Running postprocesser %s on %r',
                     yamldef['postprocess'], vars['filename'])
            postproc(os.path.join(output_dir, vars['filename']))


def is_supported(yamldef):
    try:
        subprocess.check_call(yamldef['support_check'], shell=True)
        return True
    except subprocess.CalledProcessError as e:
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('manifest')
    p.add_argument('--output', default='images',
                   help='Output directory for generated images')
    p.add_argument('--only',
                   help='Only generate this named image')
    p.add_argument('--debug', action='store_true', default=False)
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    try:
        os.mkdir(args.output)
    except FileExistsError:
        pass

    with open(args.manifest) as f:
        yamldef = yaml.load(f, Loader=yaml.SafeLoader)

    outyaml = {'images': []}

    for image in yamldef['images']:
        if args.only and args.only != image['name']:
            continue
        if 'support_check' in image and not is_supported(image):
            LOG.warning('Unable to generate image %s (%s)' % image['name'])
            continue
        if 'generated_by' in image:
            generate_one(image, args.output)
            outyaml['images'].append(image)
        else:
            LOG.error('Unknown source for image %s', image['name'])

    with open(os.path.join(args.output, 'manifest.yaml'), 'w') as f:
        yaml.dump(outyaml, f)


if __name__ == '__main__':
    sys.exit(main())
