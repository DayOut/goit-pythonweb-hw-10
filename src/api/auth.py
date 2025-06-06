from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    BackgroundTasks,
    Request,
)
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordRequestForm

from src.schemas import UserCreate, Token, User, RequestEmail
from src.services.email import send_email
from src.services.auth import create_access_token, Hash, get_email_from_token
from src.services.users import UserService
from src.database.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)


USER_EXISTS_EMAIL = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="Користувач з таким email вже існує",
)

USER_EXISTS_USERNAME = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="Користувач з таким іменем вже існує",
)

INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Неправильний логін або пароль",
    headers={"WWW-Authenticate": "Bearer"},
)

EMAIL_NOT_CONFIRMED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Електронна адреса не підтверджена",
)

VERIFICATION_ERROR = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="Verification error",
)


@router.post("/register", response_model=User, status_code=status.HTTP_201_CREATED)
async def register_user(
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    user_service: UserService = Depends(get_user_service),
):
    """Реєстрація нового користувача."""
    if await user_service.get_user_by_email(user_data.email):
        raise USER_EXISTS_EMAIL

    if await user_service.get_user_by_username(user_data.username):
        raise USER_EXISTS_USERNAME

    user_data.password = Hash().get_password_hash(user_data.password)
    new_user = await user_service.create_user(user_data)

    background_tasks.add_task(
        send_email, new_user.email, new_user.username, request.base_url
    )

    return new_user


@router.post("/login", response_model=Token)
async def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    user_service: UserService = Depends(get_user_service),
):
    """Аутентифікація користувача."""
    user = await user_service.get_user_by_username(form_data.username)

    if not user or not Hash().verify_password(form_data.password, user.hashed_password):
        raise INVALID_CREDENTIALS

    if not user.confirmed:
        raise EMAIL_NOT_CONFIRMED

    access_token = await create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/confirmed_email/{token}")
async def confirmed_email(
    token: str,
    user_service: UserService = Depends(get_user_service),
):
    """Підтвердження email через токен."""
    email = await get_email_from_token(token)
    user = await user_service.get_user_by_email(email)

    if not user:
        raise VERIFICATION_ERROR

    if user.confirmed:
        return {"message": "Ваша електронна пошта вже підтверджена"}

    await user_service.confirmed_email(email)
    return {"message": "Електронну пошту підтверджено"}


@router.post("/request_email")
async def request_email(
    body: RequestEmail,
    background_tasks: BackgroundTasks,
    request: Request,
    user_service: UserService = Depends(get_user_service),
):
    """Повторна відправка email з підтвердженням."""
    user = await user_service.get_user_by_email(body.email)

    if user and user.confirmed:
        return {"message": "Ваша електронна пошта вже підтверджена"}

    if user:
        background_tasks.add_task(
            send_email, user.email, user.username, request.base_url
        )

    return {"message": "Перевірте свою електронну пошту для підтвердження"}