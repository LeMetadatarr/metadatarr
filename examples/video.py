"""TVmaze show / season / cast lookup."""
from pytvmaze import TVmazeClient


def main() -> None:
    client = TVmazeClient()

    show = client.singlesearch("The Boys")
    if not show:
        print("no show found")
        return

    print(f"--- TVmaze: {show.name} ---")
    print(f"  id={show.id}  premiered={show.premiered}  status={show.status}")
    if show.externals:
        print(f"  imdb={show.externals.imdb}  tvdb={show.externals.thetvdb}")

    print("\n--- seasons ---")
    for s in client.get_seasons(show.id)[:5]:
        print(f"  S{s.number}  episodes={s.episode_order}  premiere={s.premiere_date}")

    print("\n--- cast (first 5) ---")
    for member in client.get_cast(show.id)[:5]:
        person = member.person.name if member.person else "?"
        print(f"  {person} as {member.character_name}")


if __name__ == "__main__":
    main()
