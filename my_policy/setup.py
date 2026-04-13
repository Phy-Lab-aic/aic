from setuptools import find_packages, setup
from glob import glob

package_name = "my_policy"

setup(
    name=package_name,
    version="0.0.2",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", glob("config/*.yaml") + glob("config/*.srdf")),
        (f"share/{package_name}/launch", glob("launch/*.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="participant",
    maintainer_email="participant@participant.com",
    description="Custom policies for AIC cable insertion",
    license="Apache-2.0",
    entry_points={},
)
