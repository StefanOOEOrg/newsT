import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { OverviewService } from '../../api/overview.service';
import { emptyOverviewFixture, overviewFixture } from '../../api/testing/fixtures';
import { Overview } from './overview';

/** In-memory `/api/overview` answer of the spec. */
class FakeOverview {
  answer = overviewFixture();
  failure: HttpErrorResponse | null = null;

  get(): Observable<ReturnType<typeof overviewFixture>> {
    return this.failure ? throwError(() => this.failure) : of(structuredClone(this.answer));
  }
}

function render(fake: FakeOverview): ComponentFixture<Overview> {
  TestBed.configureTestingModule({ providers: [{ provide: OverviewService, useValue: fake }] });
  const fixture = TestBed.createComponent(Overview);
  TestBed.tick();
  fixture.detectChanges();
  return fixture;
}

describe('Overview screen', () => {
  it('renders one card per counter of the fixture', () => {
    const el = render(new FakeOverview()).nativeElement as HTMLElement;

    expect(el.querySelector('h1')?.textContent?.trim()).toBe('Overview');
    const cards = Array.from(el.querySelectorAll('.card'));
    expect(cards).toHaveLength(7);
    expect(cards.map((card) => card.querySelector('.card-label')?.textContent?.trim())).toEqual([
      'Assets',
      'Posts',
      'Analyses',
      'Alerts',
      'Open alerts',
      'Last collector run',
      'Database size',
    ]);
    expect(cards.map((card) => card.querySelector('.card-value')?.textContent?.trim())).toEqual([
      '12',
      '4210',
      '3980',
      '57',
      '9',
      '2026-11-03 06:15',
      '4.0 MB',
    ]);
  });

  it('renders the em dash for a null field', () => {
    const fake = new FakeOverview();
    fake.answer = { ...emptyOverviewFixture(), assets: 1 };
    const el = render(fake).nativeElement as HTMLElement;

    const values = Array.from(el.querySelectorAll('.card-value')).map((node) =>
      node.textContent?.trim(),
    );
    expect(values).toEqual(['1', '0', '0', '0', '0', '—', '—']);
  });

  it('renders the empty state on an empty database instead of a grid of zeros', () => {
    const fake = new FakeOverview();
    fake.answer = emptyOverviewFixture();
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('.card')).toBeNull();
    expect(el.querySelector('[data-testid="empty"]')?.textContent).toContain('database is empty');
  });

  it('renders an error line with the status when the call fails', () => {
    const fake = new FakeOverview();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('.card')).toBeNull();
    expect(el.querySelector('[data-testid="error"]')?.textContent).toContain('HTTP 503');
  });

  it('refreshes on the button', () => {
    const fake = new FakeOverview();
    const fixture = render(fake);
    const el = fixture.nativeElement as HTMLElement;

    (el.querySelector('button') as HTMLButtonElement).click();
    TestBed.tick();
    fixture.detectChanges();

    expect(el.querySelectorAll('.card')).toHaveLength(7);
  });
});
