from setuptools import find_packages, setup

package_name = "aic_data_collection"

setup(
    name=package_name,
    version="0.0.1",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/auto_data_collection.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="AIC User",
    maintainer_email="user@example.com",
    description="Automated data collection pipeline for AIC",
    license="Apache-2.0",
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            "auto_data_collector = aic_data_collection.auto_data_collector:main",
        ],
    },
)
