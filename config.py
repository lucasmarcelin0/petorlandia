class Config:
    SECRET_KEY = "dev-key"  # substitua por uma variável segura em produção
    SQLALCHEMY_DATABASE_URI = (
        "postgresql://u82pgjdcmkbq7v:"
        "p0204cb9289674b66bfcbb9248eaf9d6a71e2dece2722fe22d6bd976c77b411e6"
        "@c2hbg00ac72j9d.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/d2nnmcuqa8ljli"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_TYPE = "filesystem"
