"""Install the offline validation tool as an ament Python package."""

from glob import glob

from setuptools import find_packages, setup

PACKAGE = "cobot_mujoco"

setup(
    name=PACKAGE,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{PACKAGE}"]),
        (f"share/{PACKAGE}", ["package.xml"]),
        (f"share/{PACKAGE}/config", glob("config/*.json")),
        (f"share/{PACKAGE}/config/textures", glob("config/textures/*")),
        (f"share/{PACKAGE}/docs", glob("docs/*")),
    ],
    package_data={PACKAGE: []},
    install_requires=["setuptools"],
    zip_safe=False,
    maintainer="HeoJiHyeok",
    maintainer_email="125938592+JiHyeokHeo@users.noreply.github.com",
    description="Offline imitation-learning comparisons and provisional OMX MuJoCo validation",
    license="Apache-2.0",
    entry_points={"console_scripts": ["cobot-mujoco = cobot_mujoco.cli:main"]},
)
