from setuptools import setup, find_packages

version = "Unknown"
for line in open("metasv/_version.py"):
    if line.startswith("__version__"):
        version = line.strip().split("=")[1].strip()

print version
setup(
      name='MetaSV',
      version=version,
      description='MetaSV: An accurate and integrative structural-variant caller for next generation sequencing',
      author='Bina Technologies',
      author_email='rd@bina.com',
      url='https://github.com/bioinform/metasv',
      packages = find_packages(),
      install_requires = ["cython", "pysam==0.7.7", "pybedtools", "pyvcf"],
      package_data = {"metasv": ["resources/*"]},
      scripts=['scripts/run_metasv.py', 'scripts/svtool_to_vcf.py', 'scripts/annotate_vcf_bam.py'],
      dependency_links = ["https://pypi.python.org/packages/source/p/pysam/pysam-0.7.7.tar.gz"]
      )
