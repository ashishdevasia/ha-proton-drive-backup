from setuptools import setup, find_packages
setup(
    name="ha-proton-drive-backup",
    packages=find_packages(),
    package_data={
        'backup': ['static/*', 'static/*/*', 'static/*/*/*']
    }
)
