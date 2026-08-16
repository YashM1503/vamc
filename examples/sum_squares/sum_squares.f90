real(kind=8) function sum_squares(n, x)
  integer, intent(in) :: n
  real(kind=8), intent(in) :: x(n)
  integer :: i
  sum_squares = 0.0d0
  do i = 1, n
    sum_squares = sum_squares + x(i) * x(i)
  end do
end function sum_squares
