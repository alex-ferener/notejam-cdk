import setuptools


with open("README.md") as fp:
    long_description = fp.read()


setuptools.setup(
    name="notejam",
    version="0.1.0",

    description="Notejam CDK Python app",
    long_description=long_description,
    long_description_content_type="text/markdown",

    author="Alexandru Ferener-Vari",

    package_dir={"": "notejam"},
    packages=setuptools.find_packages(where="notejam"),

    install_requires=[
        "aws-cdk.core==1.106.1",
        "aws-cdk.aws-cloudfront==1.106.1",
        "aws-cdk.aws-cloudfront-origins==1.106.1",
        "aws-cdk.aws-codebuild==1.106.1",
        "aws-cdk.aws-codepipeline==1.106.1",
        "aws-cdk.aws-codepipeline-actions==1.106.1",
        "aws-cdk.aws-ec2==1.106.1",
        "aws-cdk.aws-ecr==1.106.1",
        "aws-cdk.aws-ecs==1.106.1",
        "aws-cdk.aws-elasticache==1.106.1",
        "aws-cdk.aws-elasticloadbalancingv2==1.106.1",
        "aws-cdk.aws-iam==1.106.1",
        "aws-cdk.aws-rds==1.106.1",
        "aws-cdk.pipelines==1.106.1",
    ],

    python_requires=">=3.6",

    classifiers=[
        "Development Status :: 4 - Beta",

        "Intended Audience :: Developers",

        "License :: OSI Approved :: Apache Software License",

        "Programming Language :: JavaScript",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",

        "Topic :: Software Development :: Code Generators",
        "Topic :: Utilities",

        "Typing :: Typed",
    ],
)
