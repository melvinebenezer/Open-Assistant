from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from oasst_backend.api import deps
from oasst_backend.api.v1 import utils
from oasst_backend.models import ApiClient
from oasst_backend.prompt_repository import PromptRepository
from oasst_shared.exceptions.oasst_api_error import OasstError, OasstErrorCode
from oasst_shared.schemas import protocol
from sqlmodel import Session
from starlette.status import HTTP_204_NO_CONTENT

router = APIRouter()


@router.get("/", response_model=list[protocol.Message])
def query_messages(
    auth_method: Optional[str] = None,
    username: Optional[str] = None,
    api_client_id: Optional[str] = None,
    max_count: Optional[int] = Query(10, gt=0, le=1000),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    only_roots: Optional[bool] = False,
    desc: Optional[bool] = True,
    allow_deleted: Optional[bool] = False,
    api_client: ApiClient = Depends(deps.get_api_client),
    db: Session = Depends(deps.get_db),
):
    """
    Query messages.
    """
    pr = PromptRepository(db, api_client)
    messages = pr.query_messages_ordered_by_created_date(
        auth_method=auth_method,
        username=username,
        api_client_id=api_client_id,
        desc=desc,
        limit=max_count,
        gte_created_date=start_date,
        lte_created_date=end_date,
        only_roots=only_roots,
        deleted=None if allow_deleted else False,
    )

    return utils.prepare_message_list(messages)


@router.get("/cursor", response_model=protocol.MessagePage)
def get_messages_cursor(
    lt: Optional[str] = None,
    gt: Optional[str] = None,
    user_id: Optional[UUID] = None,
    auth_method: Optional[str] = None,
    username: Optional[str] = None,
    api_client_id: Optional[str] = None,
    only_roots: Optional[bool] = False,
    include_deleted: Optional[bool] = False,
    max_count: Optional[int] = Query(10, gt=0, le=1000),
    desc: Optional[bool] = False,
    api_client: ApiClient = Depends(deps.get_api_client),
    db: Session = Depends(deps.get_db),
):
    def split_cursor(x: str | None) -> tuple[datetime, UUID]:
        if not x:
            return None, None
        try:
            m = utils.split_uuid_pattern.match(x)
            if m:
                return datetime.fromisoformat(m[2]), UUID(m[1])
            return datetime.fromisoformat(x), None
        except ValueError:
            raise OasstError("Invalid cursor value", OasstErrorCode.INVALID_CURSOR_VALUE)

    lte_created_date, lt_id = split_cursor(lt)
    gte_created_date, gt_id = split_cursor(gt)

    pr = PromptRepository(db, api_client)
    messages = pr.query_messages_ordered_by_created_date(
        user_id=user_id,
        auth_method=auth_method,
        username=username,
        api_client_id=api_client_id,
        gte_created_date=gte_created_date,
        gt_id=gt_id,
        lte_created_date=lte_created_date,
        lt_id=lt_id,
        only_roots=only_roots,
        deleted=None if include_deleted else False,
        desc=desc,
        limit=max_count,
    )

    items = utils.prepare_message_list(messages)
    n, p = None, None
    if len(items) > 0:
        if len(items) == max_count or gte_created_date:
            p = str(items[0].id) + "$" + items[0].created_date.isoformat()
        if len(items) == max_count or lte_created_date:
            n = str(items[-1].id) + "$" + items[-1].created_date.isoformat()
    else:
        if gte_created_date:
            p = gte_created_date.isoformat()
        if lte_created_date:
            n = lte_created_date.isoformat()

    order = "desc" if desc else "asc"
    return protocol.MessagePage(prev=p, next=n, sort_key="created_date", order=order, items=items)


@router.get("/{message_id}", response_model=protocol.Message)
def get_message(
    message_id: UUID, api_client: ApiClient = Depends(deps.get_api_client), db: Session = Depends(deps.get_db)
):
    """
    Get a message by its internal ID.
    """
    pr = PromptRepository(db, api_client)
    message = pr.fetch_message(message_id)
    return utils.prepare_message(message)


@router.get("/{message_id}/conversation", response_model=protocol.Conversation)
def get_conv(
    message_id: UUID, api_client: ApiClient = Depends(deps.get_api_client), db: Session = Depends(deps.get_db)
):
    """
    Get a conversation from the tree root and up to the message with given internal ID.
    """

    pr = PromptRepository(db, api_client)
    messages = pr.fetch_message_conversation(message_id)
    return utils.prepare_conversation(messages)


@router.get("/{message_id}/tree", response_model=protocol.MessageTree)
def get_tree(
    message_id: UUID, api_client: ApiClient = Depends(deps.get_api_client), db: Session = Depends(deps.get_db)
):
    """
    Get all messages belonging to the same message tree.
    """
    pr = PromptRepository(db, api_client)
    message = pr.fetch_message(message_id)
    tree = pr.fetch_message_tree(message.message_tree_id, reviewed=False)
    return utils.prepare_tree(tree, message.message_tree_id)


@router.get("/{message_id}/children", response_model=list[protocol.Message])
def get_children(
    message_id: UUID, api_client: ApiClient = Depends(deps.get_api_client), db: Session = Depends(deps.get_db)
):
    """
    Get all messages belonging to the same message tree.
    """
    pr = PromptRepository(db, api_client)
    messages = pr.fetch_message_children(message_id)
    return utils.prepare_message_list(messages)


@router.get("/{message_id}/descendants", response_model=protocol.MessageTree)
def get_descendants(
    message_id: UUID, api_client: ApiClient = Depends(deps.get_api_client), db: Session = Depends(deps.get_db)
):
    """
    Get a subtree which starts with this message.
    """
    pr = PromptRepository(db, api_client)
    message = pr.fetch_message(message_id)
    descendants = pr.fetch_message_descendants(message)
    return utils.prepare_tree(descendants, message.id)


@router.get("/{message_id}/longest_conversation_in_tree", response_model=protocol.Conversation)
def get_longest_conv(
    message_id: UUID, api_client: ApiClient = Depends(deps.get_api_client), db: Session = Depends(deps.get_db)
):
    """
    Get the longest conversation from the tree of the message.
    """
    pr = PromptRepository(db, api_client)
    message = pr.fetch_message(message_id)
    conv = pr.fetch_longest_conversation(message.message_tree_id)
    return utils.prepare_conversation(conv)


@router.get("/{message_id}/max_children_in_tree", response_model=protocol.MessageTree)
def get_max_children(
    message_id: UUID, api_client: ApiClient = Depends(deps.get_api_client), db: Session = Depends(deps.get_db)
):
    """
    Get message with the most children from the tree of the provided message.
    """
    pr = PromptRepository(db, api_client)
    message = pr.fetch_message(message_id)
    message, children = pr.fetch_message_with_max_children(message.message_tree_id)
    return utils.prepare_tree([message, *children], message.id)


@router.delete("/{message_id}", status_code=HTTP_204_NO_CONTENT)
def mark_message_deleted(
    message_id: UUID, api_client: ApiClient = Depends(deps.get_trusted_api_client), db: Session = Depends(deps.get_db)
):
    pr = PromptRepository(db, api_client)
    pr.mark_messages_deleted(message_id)