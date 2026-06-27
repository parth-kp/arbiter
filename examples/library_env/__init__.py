"""A tiny lending-library environment: the worked example in docs/EXTENDING.md."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from arbiter.core.environment import Environment, RuleViolation, ToolError, predicate, tool


class Book(BaseModel):
    id: str
    title: str
    available: bool = True


class Member(BaseModel):
    id: str
    name: str
    card_pin: str
    loans: list[str] = Field(default_factory=list)


class LibraryState(BaseModel):
    books: dict[str, Book]
    members: dict[str, Member]
    verified_member: str | None = None


class MemberArgs(BaseModel):
    member_id: str
    card_pin: str


class SearchArgs(BaseModel):
    query: str


class LoanArgs(BaseModel):
    book_id: str


class PolicyArgs(BaseModel):
    query: str


class LibraryEnvironment(Environment):
    name = "library"
    description = "A lending library: search books, verify members, check books out and back in."
    State = LibraryState
    fixtures_dir = Path(__file__).parent / "fixtures"
    MAX_LOANS = 2

    @tool(mutates=True)
    def verify_member(self, args: MemberArgs) -> dict:
        """Verify a library member with their member id and card PIN. Required before any loan action."""
        m = self.state.members.get(args.member_id)
        if m is None or m.card_pin != args.card_pin:
            raise ToolError("member id or PIN is incorrect")
        self.state.verified_member = m.id
        return {"verified": True, "member": m.name}

    @tool()
    def search_books(self, args: SearchArgs) -> list[dict]:
        """Search the catalogue by title words."""
        q = args.query.lower()
        return [b.model_dump() for b in self.state.books.values() if q in b.title.lower()]

    @tool(mutates=True)
    def checkout_book(self, args: LoanArgs) -> dict:
        """Check a book out to the verified member."""
        member = self._verified()
        book = self.state.books.get(args.book_id)
        if book is None:
            raise ToolError(f"no book {args.book_id}")
        if not book.available:
            raise ToolError(f"{book.title} is already on loan")
        if len(member.loans) >= self.MAX_LOANS:
            raise RuleViolation("loan_limit", f"members may hold at most {self.MAX_LOANS} books at once")
        book.available = False
        member.loans.append(book.id)
        return {"checked_out": book.id, "loans": member.loans}

    @tool(retrieval=True)
    def search_policies(self, args: PolicyArgs) -> list[dict]:
        """Search the library's lending policies."""
        return self.policy_search(args.query)

    def _verified(self) -> Member:
        if self.state.verified_member is None:
            raise RuleViolation("verify_first", "the member must be verified before any loan action")
        return self.state.members[self.state.verified_member]

    def sensitive_values(self) -> dict[str, set[str]]:
        return {m.id: {m.card_pin} for m in self.state.members.values()}

    @predicate()
    def member_has_book(self, member_id: str, book_id: str) -> tuple[bool, str]:
        loans = self.state.members[member_id].loans
        return book_id in loans, f"{member_id} loans: {loans}"


environment = LibraryEnvironment
