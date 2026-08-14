import { Component, OnInit, OnDestroy, Input, Output, EventEmitter } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { UntilDestroy, untilDestroyed } from '@ngneat/until-destroy';
import { Subject, filter, debounceTime, tap, firstValueFrom } from 'rxjs';
import { DEFAULT_TIME_FORMATS } from '@gauzy/constants';
import { IUser, ITag, IRole, IUserUpdateInput, RolesEnum, IImageAsset } from '@gauzy/contracts';
import { patterns } from '@gauzy/constants';
import {
	AuthService,
	EmailValidator,
	ErrorHandlingService,
	MatchValidator,
	RoleService,
	Store,
	ToastrService,
	UsersService
} from '@gauzy/ui-core/core';
import { FormHelpers } from '../../forms/helpers';

@UntilDestroy({ checkProperties: true })
@Component({
	selector: 'ngx-profile',
	templateUrl: './edit-profile-form.component.html',
	styleUrls: ['./edit-profile-form.component.scss'],
	standalone: false
})
export class EditProfileFormComponent implements OnInit, OnDestroy {
	FormHelpers: typeof FormHelpers = FormHelpers;
	hoverState: boolean;
	loading: boolean;
	listOfTimeFormats = DEFAULT_TIME_FORMATS;
	role: IRole;
	user: IUser;
	user$: Subject<any> = new Subject();

	/*
	 * Getter & Setter for selected user
	 */
	_selectedUser: IUser;
	get selectedUser(): IUser {
		return this._selectedUser;
	}
	@Input() set selectedUser(value: IUser) {
		this._selectedUser = value;
	}

	/*
	 * Getter & Setter for allow role change
	 */
	_allowRoleChange: boolean = false;
	get allowRoleChange(): boolean {
		return this._allowRoleChange;
	}
	@Input() set allowRoleChange(value: boolean) {
		this._allowRoleChange = value;
	}

	@Output() userSubmitted = new EventEmitter<void>();

	/**
	 * True when the signed-in user may look at their own profile but not change it.
	 *
	 * This component serves two different screens: `/pages/auth/profile` ("my
	 * profile", where `selectedUser` is never set) and the admin's Edit User /
	 * Edit Employee form (where it is). Only the first is restricted — disabling
	 * the form outright would also break an admin editing somebody else, which is
	 * the same component instance with a different input.
	 *
	 * NOTE: this is a UI restriction, not an authorisation boundary. Gauzy's
	 * `PUT /user/:id` still lets a user update their own record, so anyone with a
	 * console can bypass the hidden button. It stops accidental edits and matches
	 * what the role is expected to be able to do; it does not enforce it. Enforcing
	 * it needs a server-side check in `packages/core`, which is a separate change.
	 */
	public isReadOnly: boolean = false;

	public form: UntypedFormGroup = EditProfileFormComponent.buildForm(this._fb);
	static buildForm(fb: UntypedFormBuilder): UntypedFormGroup {
		return fb.group(
			{
				firstName: [],
				lastName: [],
				email: [null, [Validators.required, Validators.email]],
				imageUrl: [{ value: null, disabled: true }],
				imageId: [],
				password: [],
				repeatPassword: [],
				role: [],
				tags: [],
				preferredLanguage: [],
				timeZone: [],
				timeFormat: [],
				phoneNumber: []
			},
			{
				validators: [MatchValidator.mustMatch('password', 'repeatPassword')]
			}
		);
	}

	public excludes: RolesEnum[] = [];

	constructor(
		private readonly _fb: UntypedFormBuilder,
		private readonly _authService: AuthService,
		private readonly _userService: UsersService,
		private readonly _store: Store,
		private readonly _toastrService: ToastrService,
		private readonly _errorHandler: ErrorHandlingService,
		private readonly _roleService: RoleService
	) {}

	async ngOnInit() {
		this.excludeRoles();
		this.resolveEditability();
		this.user$
			.pipe(
				debounceTime(100),
				tap(() => this.getUserProfile()),
				untilDestroyed(this)
			)
			.subscribe();
		this._store.user$
			.pipe(
				filter((user: IUser) => !!user),
				tap((user: IUser) => (this.user = user)),
				tap(() => this.user$.next(true)),
				untilDestroyed(this)
			)
			.subscribe();
	}

	/**
	 * Excludes roles based on the user's permissions.
	 * Adds the SUPER_ADMIN role to the excludes list if the user lacks SUPER_ADMIN privileges.
	 */
	async excludeRoles(): Promise<void> {
		try {
			// Check if the user has the SUPER_ADMIN role
			const hasSuperAdminRole = await firstValueFrom(this._authService.hasRole([RolesEnum.SUPER_ADMIN]));

			// Add SUPER_ADMIN to the excludes list if the user lacks the role
			if (!hasSuperAdminRole) {
				this.excludes.push(RolesEnum.SUPER_ADMIN);
			}
		} catch (error) {
			this._errorHandler?.handleError(error); // Optional error handling if applicable
		}
	}

	/**
	 * Decides whether the signed-in user may edit the profile currently on screen.
	 *
	 * Editing is reserved for SUPER_ADMIN and ADMIN. EMPLOYEE and MANAGER get the
	 * same page in read-only form. The check is by role rather than by permission
	 * because the roles are what was specified, and because no existing Gauzy
	 * permission expresses "may edit own profile" — ORG_USERS_EDIT is about
	 * editing *other* users and is not granted to an employee anyway.
	 *
	 * Disabling the form group is what makes it read-only: every control in the
	 * template binds through `formControlName`, so one call covers all of them and
	 * a field added later is covered automatically. Disabled controls keep their
	 * patched values, so the profile still displays normally.
	 */
	async resolveEditability(): Promise<void> {
		// An admin editing someone else is a different screen; leave it editable.
		if (this.selectedUser?.id) {
			return;
		}
		try {
			const canEdit = await firstValueFrom(
				this._authService.hasRole([RolesEnum.SUPER_ADMIN, RolesEnum.ADMIN])
			);
			this.isReadOnly = !canEdit;

			if (this.isReadOnly) {
				this.form.disable();
			}
		} catch (error) {
			// Fail CLOSED: if the role cannot be resolved the form stays disabled
			// rather than silently granting edit rights to whoever hit the error.
			this.isReadOnly = true;
			this.form.disable();
			this._errorHandler?.handleError(error);
		}
	}

	/**
	 * Retrieves the profile of the selected user or the current user.
	 * Fetches user details including tags and role, and updates the form.
	 */
	async getUserProfile(): Promise<void> {
		try {
			const relations = ['tags', 'role'];
			let user: IUser;

			// If a different user is selected (admin editing another user), use getUserById which requires ORG_USERS_VIEW.
			// Otherwise load the current user's own profile via /user/me which has no permission restriction.
			if (this.selectedUser?.id && this.selectedUser.id !== this.user?.id) {
				user = await this._userService.getUserById(this.selectedUser.id, relations);
			} else {
				user = await this._userService.getMe(relations);
			}

			// Patch the form with the retrieved user data
			this._patchForm({ ...user });
		} catch (error) {
			this._errorHandler?.handleError(error); // Handle errors gracefully
		}
	}

	handleImageUploadError(error: any) {
		this._toastrService.danger(error);
	}

	async updateImageAsset(image: IImageAsset) {
		// Matches the guard in submitForm(): the uploader is hidden in read-only
		// mode, but it does not go through the disabled form group, so the write
		// path needs blocking too.
		if (this.isReadOnly) {
			return;
		}
		this._store.user = {
			...this._store.user,
			imageId: image.id
		};

		let request: IUserUpdateInput = {
			imageId: image.id
		};

		if (this.allowRoleChange) {
			const { tenantId } = this._store.user;
			const role = await firstValueFrom(
				this._roleService.getRoleByOptions({
					name: this.form.get('role').value.name,
					tenantId
				})
			);

			request = {
				...request,
				role
			};
		}

		try {
			await this._userService
				.update(this.selectedUser ? this.selectedUser.id : this._store.userId, request)
				.then((res: IUser) => {
					try {
						if (res) {
							this._store.user = {
								...this._store.user,
								imageUrl: res.imageUrl
							} as IUser;
						}
						this._toastrService.success('TOASTR.MESSAGE.IMAGE_UPDATED');
					} catch (error) {
						console.log('Error while uploading profile avatar', error);
					}
				});
		} catch (error) {
			this._errorHandler.handleError(error);
		}
	}

	async submitForm() {
		// The Save button is hidden in read-only mode; this guards the other ways
		// in (a stale template, an enter key, a direct call from a test).
		if (this.isReadOnly) {
			return;
		}
		const { timeFormat, timeZone } = this.form.value;
		const { email, firstName, lastName, tags, preferredLanguage, password, phoneNumber } = this.form.value;

		if (!EmailValidator.isValid(email, patterns.email)) {
			this._toastrService.error('TOASTR.MESSAGE.EMAIL_SHOULD_BE_REAL');
			return;
		}
		let request: IUserUpdateInput = {
			email,
			firstName,
			lastName,
			tags,
			preferredLanguage,
			timeZone,
			timeFormat,
			phoneNumber
		};

		if (password) {
			request = {
				...request,
				hash: password
			};
		}

		if (this.allowRoleChange) {
			const { tenantId } = this._store.user;
			const role = await firstValueFrom(
				this._roleService.getRoleByOptions({
					name: this.form.get('role').value.name,
					tenantId
				})
			);

			request = {
				...request,
				role
			};
		}

		try {
			await this._userService
				.update(this.selectedUser ? this.selectedUser.id : this._store.userId, request)
				.then(() => {
					if ((this.selectedUser ? this.selectedUser.id : this._store.userId) === this._store.user.id) {
						this._store.user.email = request.email;
					}

					this._toastrService.success('TOASTR.MESSAGE.PROFILE_UPDATED');
					this.userSubmitted.emit();
					/**
					 * selectedUser is null for edit profile and populated in User edit
					 * Update app language when current user's profile is modified.
					 */
					if (this.selectedUser && this.selectedUser.id !== this._store.userId) {
						return;
					}
					this._store.preferredLanguage = preferredLanguage;
				});
		} catch (error) {
			this._errorHandler.handleError(error);
		}
	}

	private _patchForm(user: IUser) {
		if (!user) {
			return;
		}

		this.form.patchValue({
			firstName: user.firstName,
			lastName: user.lastName,
			email: user.email,
			imageUrl: user.imageUrl,
			imageId: user.imageId,
			role: user.role,
			tags: user.tags,
			preferredLanguage: user.preferredLanguage,
			timeZone: user.timeZone,
			timeFormat: user.timeFormat,
			phoneNumber: user.phoneNumber
		});
		this.role = user.role;
	}

	/**
	 *
	 * @param tags
	 */
	selectedTagsHandler(tags: ITag[]) {
		this.form.get('tags').setValue(tags);
		this.form.get('tags').updateValueAndValidity();
	}

	/**
	 * On Selection Change
	 * @param role
	 */
	onSelectionChange(role: IRole) {
		this.form.get('role').setValue(role);
		this.form.get('role').updateValueAndValidity();
	}

	ngOnDestroy(): void {}
}
